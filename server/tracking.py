"""Owner-triggered carrier evidence, independent of Hermes and immutable imports."""
import copy
import datetime as dt
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from core import ApiError
from client_scope import active_client
from records import records
from operations import keys, text, validate
from store import encode
from workflow import today
from msc_browser import collect, browser_path, CollectorError
from msc_tracking import parse, changes, location

PORTS = ('Onne, NG', 'Apapa, NG', 'Tincan/Lagos, NG', 'Lagos, NG', 'Lekki, NG',
         'Port Harcourt, NG', 'Warri, NG', 'Calabar, NG')


def next_slot(now):
    """Persist wall-clock check times rather than resetting an interval at every restart."""
    local = dt.datetime.fromtimestamp(now, ZoneInfo('Africa/Lagos'))
    for offset in range(2):
        day = local.date()+dt.timedelta(days=offset)
        for hour in (8, 16):
            candidate = dt.datetime.combine(day, dt.time(hour), local.tzinfo).timestamp()
            if candidate > now:
                return candidate


def msc_job(record):
    liner = str(record.get('liner', '')).upper()
    return bool(re.search(r'\bMSC\b|MEDITERRANEAN\s+SHIPPING', liner))


def field_value(data, field):
    return (data.get('closure', {}).get('empty_returns', {}).get('date') if field == 'empty_returns'
            else data['dates'].get(field))


def manual_change_since(con, identifier, field, audit_id=0):
    """A later owner correction remains an override even if it returns to the old source value."""
    for row in con.execute("SELECT action,detail FROM audit WHERE id>? AND actor!='tracking_worker' ORDER BY id", (audit_id,)):
        if row['action'].startswith('report_'):
            continue
        detail = json.loads(row['detail'])
        if detail.get('shipment_id') != identifier:
            continue
        before, after = detail.get('before'), detail.get('after')
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        if not isinstance(before.get('dates'), dict) or not isinstance(after.get('dates'), dict):
            continue
        if field_value(before, field) != field_value(after, field):
            return True
        if field == 'empty_returns' and before.get('closure', {}).get(field) != after.get('closure', {}).get(field):
            return True
    return False


def job(con, identifier):
    result = next((r for r in records(con) if r['id'] == identifier), None)
    if not result:
        raise ApiError(404, 'Shipment not found.')
    return result


def config(con, identifier):
    row = con.execute('SELECT * FROM tracking_configs WHERE shipment_id=?', (identifier,)).fetchone()
    return dict(revision=row['revision'], **json.loads(row['data'])) if row else dict(revision=0,status='not_enabled',carrier='MSC',bl='',destination='')


def command(con, action, identifier, body):
    token = text(body.get('command_id', ''), 'Command ID', 100)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', token):
        raise ApiError(400, 'A unique command_id of 16–100 safe characters is required.')
    reason = text(body.get('reason', ''), 'Reason')
    if not reason:
        raise ApiError(400, 'Record a reason for this tracking action.')
    fingerprint = hashlib.sha256(encode([action, identifier, body]).encode()).hexdigest()
    row = con.execute('SELECT * FROM commands WHERE id=?', (token,)).fetchone()
    if row and row['fingerprint'] != fingerprint:
        raise ApiError(409, 'Command ID already used with different content.')
    return token, fingerprint, reason, json.loads(row['response']) if row else None


def remember(con, token, fingerprint, response):
    con.execute('INSERT INTO commands VALUES(?,?,?)', (token, fingerprint, encode(response)))
    return response


def proposals(record, observation):
    if record['container_count'] != observation['container_count']:
        return [], 'Carrier container total differs from the job. Reconcile it before accepting dates or empty returns.'
    result = []
    for field in ('eta', 'berth', 'discharge', 'empty_returns'):
        value = observation['milestones']['empty_return' if field == 'empty_returns' else field]
        old = record['operation']['closure']['empty_returns']['date'] if field == 'empty_returns' else record['dates'].get(field)
        if value and (value != old or (field == 'empty_returns' and record['operation']['closure']['empty_returns']['applicability'] != 'required')):
            result.append(dict(field=field,before=old,after=value))
    return result, None


class Tracking:
    def __init__(self, app):
        self.app = app
        self.collector = collect
        self.lock = threading.Lock()
        self.thread = None
        self.worker = None
        self.stopping = threading.Event()
        self.include_historical = False
        self.allowed_bls = None

    def eligibility(self, record):
        if record.get('client_hidden'):
            return False, 'This client is hidden; automatic checks are paused.'
        if record['operation'].get('completed'):
            return False, 'The clearing job is already completed.'
        if not msc_job(record):
            return False, 'Automatic tracking currently supports MSC shipments only.'
        if not re.fullmatch(r'[A-Z0-9]{8,35}', record['bl'].upper().strip()):
            return False, 'The shipment BL needs correction before a carrier lookup.'
        if record.get('batch_id') and not record['operation'].get('reconciled') and not self.include_historical:
            return False, 'Historical test import: live carrier checks are excluded until the job is operationally reconciled.'
        if self.allowed_bls is not None and record['bl'].upper().strip() not in self.allowed_bls:
            return False, 'This shipment is outside the selected tracking test scope.'
        return True, 'MSC tracking runs automatically for this operational job.'

    def start_worker(self, include_historical=False, allowed_bls=None):
        """Only the serving process starts collection; constructing an app never makes network calls."""
        if self.worker and self.worker.is_alive():
            return
        self.include_historical = bool(include_historical)
        self.allowed_bls = {v.upper().strip() for v in allowed_bls} if allowed_bls is not None else None
        self.stopping.clear()
        self.worker = threading.Thread(target=self.worker_loop, name='libra-carrier-scheduler', daemon=True)
        self.worker.start()

    def stop_worker(self):
        self.stopping.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=5)

    def worker_loop(self):
        while not self.stopping.is_set():
            try:
                self.tick()
            except Exception:
                # Never include imported BLs or browser process output in a scheduler log.
                logging.warning('Carrier scheduler pass failed; persisted jobs remain due.')
            self.stopping.wait(5)

    def ensure_automatic(self, con, record):
        before = config(con, record['id'])
        bl = record['bl'].upper().strip()
        identity_changed = before.get('bl') != bl or before.get('expected_count') != record['container_count']
        if before.get('automatic') and not identity_changed:
            return before
        # Preserve an explicit pause from the earlier pilot rather than silently undoing it.
        status = before['status'] if before['status'] == 'paused' else 'active'
        if before['status']=='finished' and before.get('bl')==bl:
            previous=con.execute("SELECT observation FROM tracking_checks WHERE shipment_id=? AND status='succeeded' ORDER BY started_at DESC LIMIT 1",(record['id'],)).fetchone()
            observation=json.loads(previous[0]) if previous else {}
            if observation.get('bl')==bl and observation.get('container_count')==record['container_count'] and observation.get('milestones',{}).get('empty_return'):
                status='finished'
        data = dict(carrier='MSC',bl=bl,destination=before.get('destination', '') if before.get('bl') == bl else '',
                    status=status,automatic=True,expected_count=record['container_count'],next_due=None if status=='finished' else 0,
                    failures=0,attention=[],auto_owned=before.get('auto_owned', {}) if before.get('bl') == bl else {})
        revision = before['revision']+1
        con.execute('INSERT INTO tracking_configs VALUES(?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET revision=excluded.revision,data=excluded.data',
                    (record['id'],revision,encode(data)))
        self.app.store.audit(con,'tracking_automatic_enrolment',dict(shipment_id=record['id'],
            reason='Automatic MSC tracking for an operational job; no per-job setup is needed.',before=before,after=data),actor='tracking_worker')
        return dict(revision=revision,**data)

    def tick(self):
        """One transaction claims a due job, including across two serving processes."""
        selected = None
        now = time.time()
        with self.app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE tracking_checks SET status='failed',ended_at=?,error=? WHERE status='running' AND started_at<?",
                        (now,'Interrupted check; automatic monitoring will resume.',now-150))
            if con.execute("SELECT 1 FROM tracking_checks WHERE status='running' AND started_at>?",(now-150,)).fetchone():
                return False
            for record in records(con):
                eligible, _ = self.eligibility(record)
                if not eligible:
                    continue
                settings = self.ensure_automatic(con,record)
                if settings['status'] != 'active' or settings.get('next_due',0) > now:
                    continue
                candidate = (float(settings.get('next_due') or 0),record,settings)
                if selected is None or candidate[0] < selected[0]:
                    selected = candidate
            if not selected:
                return False
            if con.execute('SELECT 1 FROM tracking_checks WHERE started_at>?',(now-30,)).fetchone():
                return False
            _, record, settings = selected
            identifier, check_id = record['id'], uuid.uuid4().hex
            con.execute("INSERT INTO tracking_checks(id,shipment_id,config_revision,started_at,status) VALUES(?,?,?,?,'running')",
                        (check_id,identifier,settings['revision'],now))
            self.app.store.audit(con,'tracking_check_requested',dict(shipment_id=identifier,check_id=check_id,
                reason='Automatic scheduled carrier check.'),actor='tracking_worker')
        self.thread = threading.Thread(target=self.run,args=(check_id,identifier,settings),daemon=True)
        self.thread.start()
        return True

    def retry(self, identifier, body):
        keys(body, ('command_id',), 'automatic tracking check')
        request = dict(body)
        request.setdefault('command_id',uuid.uuid4().hex)
        request['reason'] = 'Owner requested a refresh of automatic carrier tracking.'
        with self.app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            token,fp,reason,replay=command(con,'tracking_automatic_retry',identifier,request)
            if replay:
                return replay
            record = job(con,identifier)
            eligible, reason = self.eligibility(record)
            if not eligible:
                raise ApiError(409,reason)
            settings = self.ensure_automatic(con,record)
            if settings['status'] != 'active':
                raise ApiError(409,'Carrier tracking is already finished or paused for this job.')
            if con.execute("SELECT 1 FROM tracking_checks WHERE status='running' AND started_at>?",(time.time()-150,)).fetchone():
                raise ApiError(409,'A carrier check is already running.')
            if con.execute('SELECT 1 FROM tracking_checks WHERE started_at>?',(time.time()-30,)).fetchone():
                raise ApiError(429,'The carrier is being checked. Wait 30 seconds before retrying.')
            check_id=uuid.uuid4().hex
            con.execute("INSERT INTO tracking_checks(id,shipment_id,config_revision,started_at,status) VALUES(?,?,?,?,'running')",
                        (check_id,identifier,settings['revision'],time.time()))
            self.app.store.audit(con,'tracking_check_requested',dict(shipment_id=identifier,check_id=check_id,reason=reason))
            response=remember(con,token,fp,{'check_id':check_id,'status':'running'})
        self.thread=threading.Thread(target=self.run,args=(check_id,identifier,settings),daemon=True)
        self.thread.start()
        return response

    def read(self, identifier):
        with self.app.store.connect() as con:
            record = job(con, identifier)
            settings = config(con, identifier)
            # A killed container must not leave an unfinishable "running" card forever.
            con.execute("UPDATE tracking_checks SET status='failed',ended_at=?,error=? WHERE shipment_id=? AND status='running' AND started_at<?",
                        (time.time(), 'Check interrupted; previous evidence is retained and automatic monitoring will resume.', identifier, time.time()-150))
            checks = []
            for row in con.execute('SELECT * FROM tracking_checks WHERE shipment_id=? ORDER BY started_at DESC LIMIT 20', (identifier,)):
                check = dict(row)
                check.pop('raw_text')
                for key in ('observation','changes','review'):
                    check[key] = json.loads(check[key]) if check[key] else None
                checks.append(check)
            latest = next((c for c in checks if c['status'] == 'succeeded'), None)
            if latest is None:
                previous = con.execute("SELECT * FROM tracking_checks WHERE shipment_id=? AND status='succeeded' ORDER BY started_at DESC LIMIT 1",(identifier,)).fetchone()
                if previous:
                    latest=dict(previous)
                    latest.pop('raw_text')
                    for key in ('observation','changes','review'):
                        latest[key]=json.loads(latest[key]) if latest[key] else None
            pending, blocked = (proposals(record, latest['observation']) if latest else ([], None))
            stale = (settings['revision'] > 0 and settings['bl'] != record['bl'].upper().strip()) or (latest and (
                latest['observation']['bl'] != settings['bl'] or
                location(latest['observation']['destination']) != location(settings['destination']) or
                (not latest['review'] and latest['config_revision'] != settings['revision'])))
            if stale:
                pending, blocked = [], 'Shipment identity changed. Automatic monitoring will refresh its carrier evidence.'
            if latest and latest['review']:
                pending = []
            eligible, eligibility_reason = self.eligibility(record)
            service_running = bool(self.worker and self.worker.is_alive() and not self.stopping.is_set())
            running = any(c['status']=='running' for c in checks)
            attention = settings.get('attention',[])
            status = ('historical' if not eligible and 'Historical' in eligibility_reason else
                      'unsupported' if not msc_job(record) else
                      'disabled' if not eligible or settings['status']=='paused' else
                      'finished' if settings['status']=='finished' else
                      'checking' if running else
                      'needs_attention' if settings.get('last_error') or attention else
                      'monitoring' if service_running else 'disabled')
            return dict(config=settings,checks=checks,latest=latest,proposals=pending,blocked=blocked,
                        shipment_revision=record['revision'],ports=PORTS,scheduled=bool(service_running and eligible and settings['status']=='active'),
                        automatic=True,eligible=eligible,eligibility_reason=eligibility_reason,status=status,
                        next_due=settings.get('next_due') if eligible and settings['status']=='active' else None,
                        attention=attention,service_running=service_running,
                        browser_available=bool(browser_path()),source_url='https://www.msc.com/en/track-a-shipment')

    def summary(self, scoped_records):
        """An overview never discovers/enrols jobs or performs a carrier request."""
        scoped = {r['id']:r for r in scoped_records}
        monitored, finished, attention = 0, 0, []
        with self.app.store.connect() as con:
            for row in con.execute('SELECT shipment_id,data FROM tracking_configs'):
                record = scoped.get(row['shipment_id'])
                if record is None:
                    continue
                settings = json.loads(row['data'])
                eligible, _ = self.eligibility(record)
                if settings['status']=='finished':
                    finished += 1
                elif settings.get('automatic') and settings['status']=='active' and eligible:
                    monitored += 1
                issues = settings.get('attention') or []
                message = settings.get('last_error') or (issues[0]['message'] if issues else None)
                if message:
                    attention.append(dict(shipment_id=record['id'],bl=record['bl'],
                        client_name=record['client_name'],message=message))
        return dict(service_running=bool(self.worker and self.worker.is_alive() and not self.stopping.is_set()),
                    monitored_count=monitored,finished_count=finished,attention_count=len(attention),attention=attention[:20])

    def configure(self, identifier, body):
        keys(body, ('command_id','reason','revision','shipment_revision','status','destination','confirm_source'), 'tracking setup')
        with self.app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            token, fp, reason, replay = command(con, 'tracking_setup', identifier, body)
            if replay:
                return replay
            record = job(con, identifier)
            active_client(con, record['client_id'])
            before = config(con, identifier)
            if type(body.get('revision')) is not int or body['revision'] != before['revision'] or type(body.get('shipment_revision')) is not int or body['shipment_revision'] != record['revision']:
                raise ApiError(409, 'Job or tracking setup changed. Reopen before saving.')
            if body.get('status') not in ('active','paused') or body.get('destination') not in PORTS:
                raise ApiError(400, 'Select an allowed Nigerian port and Active or Paused.')
            bl = record['bl'].upper().strip()
            if not re.fullmatch(r'[A-Z0-9]{8,35}', bl):
                raise ApiError(422, 'This BL format needs review before MSC lookup.')
            if body['status'] == 'active' and body.get('confirm_source') is not True:
                raise ApiError(400, 'Confirm this job may be looked up on MSC. Historical jobs are never enrolled automatically.')
            if con.execute("SELECT 1 FROM tracking_checks WHERE shipment_id=? AND status='running' AND started_at>?", (identifier,time.time()-150)).fetchone():
                raise ApiError(409, 'Wait for the running check before changing tracking setup.')
            after = dict(carrier='MSC',bl=bl,destination=body['destination'],status=body['status'])
            con.execute('INSERT INTO tracking_configs VALUES(?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET revision=excluded.revision,data=excluded.data',
                        (identifier,before['revision']+1,encode(after)))
            self.app.store.audit(con, 'tracking_setup', dict(shipment_id=identifier,reason=reason,before=before,after=after))
            return remember(con,token,fp,{'configured':True})

    def start(self, identifier, body):
        keys(body, ('command_id','reason','revision','shipment_revision'), 'tracking check')
        with self.app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            token, fp, reason, replay = command(con, 'tracking_check', identifier, body)
            if replay:
                return replay
            record, settings = job(con, identifier), config(con, identifier)
            active_client(con, record['client_id'])
            if type(body.get('revision')) is not int or body['revision'] != settings['revision'] or type(body.get('shipment_revision')) is not int or body['shipment_revision'] != record['revision']:
                raise ApiError(409, 'Job or tracking setup changed. Reopen before checking.')
            if settings['status'] != 'active' or settings['bl'] != record['bl'].upper().strip():
                raise ApiError(409, 'Enable tracking for the current BL before checking.')
            if con.execute("SELECT 1 FROM tracking_checks WHERE status='running' AND started_at>?", (time.time()-150,)).fetchone():
                raise ApiError(409, 'A carrier check is already running. Wait for it to finish.')
            if con.execute('SELECT 1 FROM tracking_checks WHERE started_at>?', (time.time()-30,)).fetchone():
                raise ApiError(429, 'Wait 30 seconds between carrier checks.')
            check_id = uuid.uuid4().hex
            con.execute("INSERT INTO tracking_checks(id,shipment_id,config_revision,started_at,status) VALUES(?,?,?,?,'running')",
                        (check_id,identifier,settings['revision'],time.time()))
            self.app.store.audit(con,'tracking_check_requested',dict(shipment_id=identifier,check_id=check_id,reason=reason))
            response = remember(con,token,fp,{'check_id':check_id,'status':'running'})
        self.thread = threading.Thread(target=self.run,args=(check_id,identifier,settings),daemon=True)
        self.thread.start()
        return response

    def run(self, check_id, identifier, settings):
        raw = None
        try:
            with self.lock:
                raw = self.collector(settings['bl'])
                observation = parse(raw,settings['bl'],None if settings.get('automatic') else settings['destination'],today())
                observation['collection_method'] = 'isolated_browser'
            with self.app.store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                check=con.execute('SELECT status FROM tracking_checks WHERE id=?',(check_id,)).fetchone()
                if not check or check[0]!='running':
                    return
                prior = con.execute("SELECT observation FROM tracking_checks WHERE shipment_id=? AND status='succeeded' ORDER BY started_at DESC LIMIT 1",(identifier,)).fetchone()
                prior_observation = json.loads(prior[0]) if prior else None
                if prior_observation and prior_observation['bl'] != observation['bl']:
                    prior_observation = None
                delta = changes(prior_observation, observation)
                review = None
                if settings.get('automatic'):
                    review = self.apply_automatic(con,identifier,check_id,settings,observation,prior_observation)
                con.execute("UPDATE tracking_checks SET status='succeeded',ended_at=?,observation=?,raw_text=?,changes=? WHERE id=? AND status='running'",
                            (time.time(),encode(observation),raw,encode(delta),check_id))
                if review:
                    con.execute('UPDATE tracking_checks SET review=? WHERE id=?',(encode(review),check_id))
                self.app.store.audit(con,'tracking_check_succeeded',dict(shipment_id=identifier,check_id=check_id,changes=delta),actor='tracking_worker')
        except Exception as exc:
            message = str(exc) if isinstance(exc, CollectorError) else 'Collector failed. Check the local runtime; previous tracking evidence is retained.'
            if raw is None:
                raw = getattr(exc,'evidence_text',None)
            logging.warning('MSC tracking check failed (%s)', type(exc).__name__)
            with self.app.store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                check=con.execute('SELECT status FROM tracking_checks WHERE id=?',(check_id,)).fetchone()
                if not check or check[0]!='running':
                    return
                code = getattr(exc,'code','collector_failed')
                diagnostic = getattr(exc,'diagnostic',None)
                con.execute("UPDATE tracking_checks SET status='failed',ended_at=?,error=?,raw_text=?,changes=? WHERE id=? AND status='running'",
                            (time.time(),message,raw,encode(dict(new_events=[],removed_events=[],milestones=[],error_code=code,diagnostic=diagnostic)),check_id))
                current = config(con,identifier)
                if settings.get('automatic') and current['revision'] == settings['revision']:
                    data = {k:v for k,v in current.items() if k!='revision'}
                    data['failures'] = min(20,int(data.get('failures',0))+1)
                    delay = min(6*3600,15*60*(2**min(data['failures']-1,5)))
                    if code in ('access_denied','challenge','verification_required','page_changed','browser_unavailable'):
                        delay = 6*3600
                    data.update(last_error=message,error_code=code,diagnostic=diagnostic,next_due=time.time()+delay)
                    con.execute('UPDATE tracking_configs SET data=? WHERE shipment_id=?',(encode(data),identifier))
                self.app.store.audit(con,'tracking_check_failed',dict(shipment_id=identifier,check_id=check_id,error=message),actor='tracking_worker')

    def apply_automatic(self, con, identifier, check_id, settings, observation, previous):
        """Routine carrier facts flow automatically; independent human edits remain authoritative."""
        current = config(con,identifier)
        record = job(con,identifier)
        info = {k:v for k,v in current.items() if k!='revision'}
        conflicts, applied = [], []
        eligible, reason = self.eligibility(record)
        if current['revision'] != settings['revision'] or record['bl'].upper().strip() != observation['bl'] or not eligible:
            conflicts.append(dict(field='identity',message='Job identity or eligibility changed during the check; no job facts were updated.',current=record['bl'],reported=observation['bl']))
            if current['revision'] == settings['revision']:
                info.update(attention=conflicts,next_due=next_slot(time.time()))
                con.execute('UPDATE tracking_configs SET data=? WHERE shipment_id=?',(encode(info),identifier))
            return dict(decision='automatic',fields=[],conflicts=conflicts,at=time.time())
        if info.get('destination') and location(info['destination']) != location(observation['destination']):
            conflicts.append(dict(field='destination',message='MSC reports a different destination; existing job dates were retained.',current=info['destination'],reported=observation['destination']))
        else:
            info['destination']=observation['destination']
        candidates, blocked = proposals(record,observation)
        if blocked:
            conflicts.append(dict(field='container_count',message=blocked,current=record['container_count'],reported=observation['container_count']))
        before, data = copy.deepcopy(record['operation']), copy.deepcopy(record['operation'])
        owned = info.setdefault('auto_owned',{})
        if not conflicts:
            for proposal in candidates:
                field, value = proposal['field'], proposal['after']
                old = field_value(data,field)
                provenance = owned.get(field,{})
                changed_by_owner = manual_change_since(con,identifier,field,provenance.get('audit_id',0))
                seeded = record.get('effective_source',{}).get('dates',{}).get(field) == old and old is not None
                source_owned = bool(provenance) and old == provenance.get('value')
                if changed_by_owner or (old is not None and not source_owned and not seeded) or (field=='empty_returns' and data['closure']['empty_returns']['applicability']=='not_applicable'):
                    conflicts.append(dict(field=field,message='An owner value or decision was retained instead of replacing it with the carrier report.',current=old,reported=value))
                    continue
                candidate = copy.deepcopy(data)
                if field=='empty_returns':
                    candidate['closure'][field].update(applicability='required',date=value,reason='MSC confirms destination empty return for every expected container.')
                else:
                    candidate['dates'][field]=value
                    if field in ('berth','discharge'):
                        candidate['arrival_basis']='discharge'
                try:
                    validate(record,candidate,record['movements'],'')
                except ApiError as exc:
                    conflicts.append(dict(field=field,message='Carrier fact retained as evidence: '+exc.message,current=old,reported=value))
                    continue
                data=candidate
                applied.append(field)
        if previous:
            for field in ('berth','discharge','empty_return'):
                if previous['milestones'].get(field) and not observation['milestones'].get(field):
                    conflicts.append(dict(field=field,message='MSC no longer lists previously reported actual evidence. The saved job fact was retained.',current=previous['milestones'][field],reported=None))
        if applied:
            revision = record['revision']+1
            con.execute('INSERT INTO job_updates VALUES(?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET revision=excluded.revision,data=excluded.data',
                        (identifier,revision,encode(data)))
            self.app.store.audit(con,'tracking_automatic_update',dict(shipment_id=identifier,check_id=check_id,
                reason='Automatic update from validated MSC destination tracking evidence.',before=before,after=data,revision=revision),actor='tracking_worker')
            audit_id=con.execute('SELECT MAX(id) FROM audit').fetchone()[0]
            for field in applied:
                owned[field]=dict(value=field_value(data,field),audit_id=audit_id,revision=revision,check_id=check_id)
        finished = observation['container_count']==record['container_count'] and observation['milestones'].get('empty_return') and not any(c['field'] in ('identity','destination','container_count') for c in conflicts)
        info.update(status='finished' if finished else 'active',failures=0,last_error=None,error_code=None,
                    diagnostic=None,attention=conflicts,next_due=None if finished else next_slot(time.time()),
                    last_success=time.time(),last_check_id=check_id)
        con.execute('UPDATE tracking_configs SET data=? WHERE shipment_id=?',(encode(info),identifier))
        return dict(decision='automatic',fields=applied,conflicts=conflicts,at=time.time())

    def capture(self, identifier, body):
        """An explicit manual capture keeps MSC access challenges outside the application."""
        keys(body, ('command_id','reason','revision','shipment_revision','source_text'), 'MSC capture')
        with self.app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            token, fp, reason, replay = command(con,'tracking_capture',identifier,body)
            if replay:
                return replay
            record, settings = job(con,identifier), config(con,identifier)
            active_client(con,record['client_id'])
            if type(body.get('revision')) is not int or body['revision'] != settings['revision'] or type(body.get('shipment_revision')) is not int or body['shipment_revision'] != record['revision']:
                raise ApiError(409,'Job or tracking setup changed. Reopen before capturing.')
            if settings['status'] != 'active' or settings['bl'] != record['bl'].upper().strip():
                raise ApiError(409,'Enable tracking for the current BL before capturing.')
            if con.execute("SELECT 1 FROM tracking_checks WHERE shipment_id=? AND status='running' AND started_at>?",(identifier,time.time()-150)).fetchone():
                raise ApiError(409,'Wait for the running check to finish before capturing.')
            raw = body.get('source_text')
            try:
                observation = parse(raw,settings['bl'],settings['destination'],today())
            except CollectorError as exc:
                raise ApiError(422,str(exc))
            observation['collection_method'] = 'owner_pasted_text'
            previous=con.execute("SELECT observation FROM tracking_checks WHERE shipment_id=? AND status='succeeded' ORDER BY started_at DESC LIMIT 1",(identifier,)).fetchone()
            delta=changes(json.loads(previous[0]) if previous else None,observation)
            check_id, now = uuid.uuid4().hex, time.time()
            con.execute("INSERT INTO tracking_checks(id,shipment_id,config_revision,started_at,ended_at,status,observation,raw_text,changes) VALUES(?,?,?,?,?,'succeeded',?,?,?)",
                        (check_id,identifier,settings['revision'],now,now,encode(observation),raw,encode(delta)))
            self.app.store.audit(con,'tracking_manual_capture',dict(shipment_id=identifier,check_id=check_id,reason=reason,changes=delta))
            return remember(con,token,fp,{'check_id':check_id,'status':'succeeded'})

    def review(self, identifier, check_id, body):
        keys(body, ('command_id','reason','revision','config_revision','decision','fields'), 'tracking review')
        with self.app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            token, fp, reason, replay = command(con,'tracking_review:'+check_id,identifier,body)
            if replay:
                return replay
            record, settings = job(con,identifier), config(con,identifier)
            active_client(con,record['client_id'])
            if type(body.get('revision')) is not int or body['revision'] != record['revision'] or type(body.get('config_revision')) is not int or body['config_revision'] != settings['revision']:
                raise ApiError(409,'Job or tracking setup changed. Reopen the review.')
            row = con.execute('SELECT * FROM tracking_checks WHERE id=? AND shipment_id=?',(check_id,identifier)).fetchone()
            latest = con.execute("SELECT id FROM tracking_checks WHERE shipment_id=? AND status='succeeded' ORDER BY started_at DESC LIMIT 1",(identifier,)).fetchone()
            if not row or row['status'] != 'succeeded' or not latest or latest[0] != check_id or row['review']:
                raise ApiError(409,'Review only the latest successful, unreviewed observation.')
            observation = json.loads(row['observation'])
            if row['config_revision'] != settings['revision'] or observation['bl'] != record['bl'].upper().strip():
                raise ApiError(409,'Tracking identity changed. Check again before applying.')
            decision = body.get('decision')
            if decision not in ('accept','reject'):
                raise ApiError(400,'Choose accept or reject.')
            fields = body.get('fields',[])
            if not isinstance(fields,list) or any(not isinstance(k,str) for k in fields) or len(fields)!=len(set(fields)):
                raise ApiError(400,'Supply distinct review fields.')
            candidates, blocked = proposals(record,observation)
            selected = {p['field']:p['after'] for p in candidates}
            if decision=='accept':
                if blocked or not fields or any(k not in selected for k in fields):
                    raise ApiError(422,blocked or 'Select available proposed changes only.')
                before, data = copy.deepcopy(record['operation']), copy.deepcopy(record['operation'])
                if any(k in fields for k in ('berth','discharge')):
                    data['arrival_basis']='discharge'
                for key in fields:
                    if key=='empty_returns':
                        data['closure']['empty_returns'].update(applicability='required',date=selected[key],reason=reason)
                    else:
                        data['dates'][key]=selected[key]
                validate(record,data,record['movements'],'')
                con.execute('INSERT INTO job_updates VALUES(?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET revision=excluded.revision,data=excluded.data',
                            (identifier,record['revision']+1,encode(data)))
                self.app.store.audit(con,'tracking_dates_accepted',dict(shipment_id=identifier,check_id=check_id,reason=reason,before=before,after=data,revision=record['revision']+1))
                if 'empty_returns' in fields:
                    updated = {k:v for k,v in settings.items() if k!='revision'}
                    updated['status']='finished'
                    con.execute('UPDATE tracking_configs SET revision=revision+1,data=? WHERE shipment_id=?',(encode(updated),identifier))
            review = dict(decision=decision,fields=fields if decision=='accept' else [],reason=reason,at=time.time())
            con.execute('UPDATE tracking_checks SET review=? WHERE id=?',(encode(review),check_id))
            self.app.store.audit(con,'tracking_review',dict(shipment_id=identifier,check_id=check_id,**review))
            return remember(con,token,fp,{'reviewed':True,'decision':decision})


def register(route, ApiError):
    def identifier(req):
        try:
            return int(req.path_params['id'])
        except ValueError:
            raise ApiError(404,'Shipment not found.')

    @route('GET','/api/shipments/<id>/tracking')
    def read(req,query,body):
        return {'tracking':req.app.tracking.read(identifier(req))}

    @route('POST','/api/shipments/<id>/tracking/config')
    def configure(req,query,body):
        return req.app.tracking.configure(identifier(req),body)

    @route('POST','/api/shipments/<id>/tracking/check')
    def check(req,query,body):
        if set(body).issubset({'command_id'}):
            return req.app.tracking.retry(identifier(req),body)
        return req.app.tracking.start(identifier(req),body)

    @route('POST','/api/shipments/<id>/tracking/capture')
    def capture(req,query,body):
        return req.app.tracking.capture(identifier(req),body)

    @route('POST','/api/shipments/<id>/tracking/<check>/review')
    def review(req,query,body):
        return req.app.tracking.review(identifier(req),req.path_params['check'],body)

    @route('GET','/api/shipments/<id>/tracking/<check>/evidence')
    def evidence(req,query,body):
        with req.app.store.connect() as con:
            job(con,identifier(req))
            row=con.execute('SELECT raw_text FROM tracking_checks WHERE id=? AND shipment_id=?',(req.path_params['check'],identifier(req))).fetchone()
            if not row:
                raise ApiError(404,'Tracking evidence not found.')
            return {'text':row[0] or ''}
