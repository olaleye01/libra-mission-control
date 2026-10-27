"""Owner-only, transactional application actions reusable by future adapters."""
import copy
import datetime as dt
import hashlib
import json
import re
import time
import uuid

from core import ApiError
from records import records
from coordination import TEAMS, STATUSES, CATEGORIES, BLOCK_STEPS, holds
from store import encode
from workflow import (TEXT_FIELDS, DATE_KEYS, INVOICE_KEYS, CLOSURE_KEYS, ACTION_KEYS,
                      initial, derive, active_events, movement_problems, today)


def text(value, name, limit=500):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ApiError(400, name+' must be text of at most '+str(limit)+' characters.')
    return value.strip()


def date(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ApiError(400, 'Dates must be YYYY-MM-DD or empty.')
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, 'Invalid calendar date.')
    return value


def count(value, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not int or not 1 <= value <= 100000:
        raise ApiError(400, 'Container counts must be integers from 1 to 100000.')
    return value


def keys(value, allowed, name):
    if not isinstance(value, dict) or set(value)-set(allowed):
        raise ApiError(400, 'Unknown or invalid '+name+' fields.')


def choice(value, allowed, name):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(400, 'Invalid '+name+'.')
    return value


def patch(data, changes):
    keys(changes, (*TEXT_FIELDS, 'container_count', 'dates', 'reconciled', 'awaiting_duty_receipt', 'approval_by', 'rotation', 'invoices', 'closure', 'completed', 'release_coverage'), 'shipment')
    for key, val in changes.items():
        if key in TEXT_FIELDS or key == 'approval_by':
            data[key] = text(val, key, 2000 if key == 'description' else 160)
        elif key == 'container_count':
            data[key] = count(val, True)
        elif key in ('reconciled', 'awaiting_duty_receipt', 'completed'):
            if type(val) is not bool:
                raise ApiError(400, key+' must be true or false.')
            data[key] = val
        elif key == 'dates':
            keys(val, DATE_KEYS, 'date')
            data[key].update({k: date(v) for k, v in val.items()})
        elif key == 'rotation':
            keys(val, ('status', 'number'), 'rotation')
            if 'status' in val:
                data[key]['status'] = choice(val['status'], ('unknown', 'not_requested', 'gotten'), 'rotation status')
            if 'number' in val:
                data[key]['number'] = text(val['number'], 'Rotation number', 160)
        elif key == 'release_coverage':
            keys(val, ('do', 'tdo', 'customs_release'), 'release coverage')
            data.setdefault(key, {}).update({k: count(v, True) for k, v in val.items()})
        elif key == 'invoices':
            keys(val, INVOICE_KEYS, 'invoice')
            for kind, fields in val.items():
                item = data[key][kind]
                keys(fields, item.keys(), 'invoice')
                for name, value in fields.items():
                    if name in ('received', 'payment_date', 'rated_through'):
                        item[name] = date(value)
                    elif name == 'reason':
                        item[name] = text(value, 'Applicability reason')
                    else:
                        options = {'request': ('unknown', 'not_requested', 'requested'), 'payment': ('unknown', 'not_paid', 'paid'),
                                   'coverage': (kind, 'combined') if kind in ('shipping', 'terminal') else ('additional',),
                                   'applicability': ('unknown', 'required', 'not_applicable')}
                        item[name] = choice(value, options[name], name)
        elif key == 'closure':
            keys(val, CLOSURE_KEYS, 'closure')
            for kind, fields in val.items():
                keys(fields, ('applicability', 'date', 'reason'), 'closure item')
                for name, value in fields.items():
                    data[key][kind][name] = date(value) if name == 'date' else text(value, 'Applicability reason') if name == 'reason' else choice(value, ('unknown', 'required', 'not_applicable'), 'applicability')
    if 'handler' in changes and 'field_agent' in changes and data['handler'] != data['field_agent']:
        raise ApiError(422, 'File Handler is the Field Agent. Supply one consistent assignment.')
    if 'handler' in changes or 'field_agent' in changes:
        agent = data['field_agent'] if 'field_agent' in changes else data['handler']
        data['field_agent'] = data['handler'] = agent
        data['legacy_handler'] = ''
    if not data['bl']:
        raise ApiError(400, 'A Bill of Lading is required.')
    for item in list(data['invoices'].values()) + list(data['closure'].values()):
        if item['applicability'] == 'not_applicable' and not item['reason']:
            raise ApiError(400, 'Not-applicable decisions require a reason.')
    for item in data['invoices'].values():
        if item['payment_date'] and item['payment'] != 'paid':
            raise ApiError(422, 'A payment date requires an explicitly reported paid status.')
    if data['dates']['draft_approved']:
        if not data['dates']['draft_received'] or not data['approval_by']:
            raise ApiError(422, 'Record the actual draft receipt and approver for an approval date.')
        if data['dates']['draft_approved'] < data['dates']['draft_received']:
            raise ApiError(422, 'Draft approval cannot precede draft receipt.')


def validate(record, data, events, exception_reason):
    active = active_events(events)
    if events and not data['reconciled']:
        raise ApiError(422, 'Reconcile the job before recording or changing movements.')
    for kind in ('gate_out', 'warehouse'):
        total = sum(e['quantity'] for e in active if e['kind'] == kind)
        if total and (data['container_count'] is None or total > data['container_count']):
            raise ApiError(422, 'Movement totals cannot exceed a known container total.')
    for key, value in data.get('release_coverage', {}).items():
        if value and (data['container_count'] is None or value > data['container_count']):
            raise ApiError(422, 'Release coverage cannot exceed a known container total.')
        if value and not data['dates'][key]:
            raise ApiError(422, 'Release coverage needs the corresponding release date.')
    candidate = derive(record, data, events, True)
    problems = [i['message'] for i in candidate['issues'] if i['code'] == 'operational_release_review']
    if problems and not exception_reason:
        raise ApiError(422, problems[0]+' To retain an observed conflicting fact, supply an exception reason.')
    if data['completed'] and candidate['closure_missing']:
        raise ApiError(422, 'Completion blocked: '+', '.join(candidate['closure_missing'])+'.')
    return candidate


def enforce_hold(data, step, exception):
    if holds(data, step) and not exception:
        raise ApiError(422, 'An owner-recorded '+BLOCK_STEPS[step]+' hold is open. Resolve it first, or supply an exception reason only to retain an observed fact.')


def update_coordination(data, identifier, fields):
    allowed = ('title', 'category', 'team', 'responsible', 'authority', 'status', 'blocker', 'next_action',
               'source', 'blocks_step', 'resolution_note', 'resolution_date')
    keys(fields, allowed, 'coordination item')
    if identifier:
        if not isinstance(identifier, str) or identifier not in data['coordination']:
            raise ApiError(404, 'Coordination item not found on this shipment.')
        item = copy.deepcopy(data['coordination'][identifier])
    else:
        if len(data['coordination']) >= 500:
            raise ApiError(422, 'This job has reached the 500-item coordination limit.')
        identifier = uuid.uuid4().hex
        item = dict(id=identifier, title='', category='clearing', team='import_officer', responsible='', authority='',
                    status='open', blocker='', next_action='', source='', blocks_step='', resolution_note='',
                    resolution_date=None, created_at=time.time())
    for key, value in fields.items():
        if key in ('category', 'team', 'status', 'blocks_step'):
            options = {'category': CATEGORIES, 'team': TEAMS, 'status': STATUSES, 'blocks_step': BLOCK_STEPS}
            item[key] = choice(value, options[key], key)
        elif key == 'resolution_date':
            item[key] = date(value)
        else:
            item[key] = text(value, key, 1000 if key in ('blocker', 'next_action', 'resolution_note') else 500)
    if not item['title'] or not item['next_action'] or not item['source']:
        raise ApiError(400, 'A coordination item needs a title, next action and supporting source.')
    if item['resolution_date'] and item['resolution_date'] > today():
        raise ApiError(400, 'A resolution date cannot be in the future.')
    if item['status'] == 'resolved' and (not item['resolution_note'] or not item['resolution_date']):
        raise ApiError(422, 'Resolved items require a resolution note and date.')
    item['updated_at'] = time.time()
    data['coordination'][identifier] = item
    return identifier


def execute(app, operation, body, identifier=None):
    keys(body, ('command_id', 'revision', 'reason', 'changes', 'client_id', 'duplicate_reason', 'exception_reason', 'kind', 'quantity', 'date', 'supersedes', 'confirm_duplicate', 'key', 'status', 'responsible', 'blocker', 'next_action', 'source', 'team', 'item_id', 'item'), 'command')
    token = text(body.get('command_id', ''), 'Command ID', 100)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', token):
        raise ApiError(400, 'A unique command_id of 16–100 safe characters is required.')
    reason = text(body.get('reason', ''), 'Change reason')
    if not reason:
        raise ApiError(400, 'A change reason is required.')
    exception = text(body.get('exception_reason', ''), 'Exception reason')
    fingerprint = hashlib.sha256(encode([operation, identifier, body]).encode()).hexdigest()
    with app.store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute('SELECT * FROM commands WHERE id=?', (token,)).fetchone()
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise ApiError(409, 'Command ID already used with different content.')
            return json.loads(previous['response'])
        all_jobs = records(con)
        if operation == 'create':
            client_id = body.get('client_id')
            if type(client_id) is not int or not con.execute('SELECT 1 FROM clients WHERE id=?', (client_id,)).fetchone():
                raise ApiError(400, 'Select an existing client.')
            data = initial({}, True)
            patch(data, body.get('changes', {}))
            record = {'dates': {}, 'issues': [], 'comments': '', 'client_id': client_id, 'batch_id': None}
            events = []
            validate(record, data, events, exception)
            cursor = con.execute('INSERT INTO shipments(client_id,created_at) VALUES(?,?)', (client_id, time.time()))
            identifier = cursor.lastrowid
            revision, before = 0, None
        else:
            record = next((r for r in all_jobs if r['id'] == identifier), None)
            if not record:
                raise ApiError(404, 'Shipment not found.')
            if type(body.get('revision')) is not int or body['revision'] != record['revision']:
                raise ApiError(409, 'Shipment changed. Reopen it before saving; your edit was not applied.')
            data, events = copy.deepcopy(record['operation']), copy.deepcopy(record['movements'])
            revision, before = record['revision'], copy.deepcopy(data)
            if operation == 'update':
                patch(data, body.get('changes', {}))
                if data['dates']['tdo'] and data['dates']['tdo'] != before['dates']['tdo']:
                    enforce_hold(data, 'tdo', exception)
                validate(record, data, events, exception)
            elif operation == 'movement':
                kind = choice(body.get('kind'), ('gate_out', 'warehouse'), 'movement type')
                event_date = date(body.get('date'))
                if not event_date or event_date > today():
                    raise ApiError(400, 'An actual movement date is required and cannot be in the future.')
                qty = body.get('quantity')
                supersedes = body.get('supersedes') or None
                if qty == 0 and type(qty) is int and supersedes:
                    pass
                else:
                    count(qty)
                if supersedes:
                    old = next((e for e in events if e['id'] == supersedes), None)
                    if not old or old['kind'] != kind or any(e['supersedes'] == supersedes for e in events):
                        raise ApiError(409, 'Correction must replace an active event of the same type on this job.')
                if not data['reconciled']:
                    raise ApiError(422, 'Confirm the historical quantity reconciliation before entering movements.')
                duplicates = [e for e in active_events(events) if e['kind'] == kind and e['date'] == event_date and e['quantity'] == qty and e['id'] != supersedes]
                if duplicates and body.get('confirm_duplicate') is not True:
                    raise ApiError(409, 'An identical-looking movement exists. Confirm a separate load explicitly or correct its event.')
                if qty > 0:
                    enforce_hold(data, kind, exception)
                event = {'id': uuid.uuid4().hex, 'shipment_id': identifier, 'kind': kind, 'date': event_date, 'quantity': qty,
                         'supersedes': supersedes, 'exception_reason': exception, 'created_at': time.time()}
                events.append(event)
                validate(record, data, events, exception)
                con.execute('INSERT INTO movements VALUES(?,?,?,?,?,?,?,?)', tuple(event[k] for k in ('id', 'shipment_id', 'kind', 'quantity', 'date', 'supersedes', 'exception_reason', 'created_at')))
            elif operation == 'followup':
                key = choice(body.get('key'), ACTION_KEYS, 'follow-up')
                status = choice(body.get('status'), ('open', 'in_progress', 'awaiting_response'), 'follow-up status')
                data['followups'][key] = {'status': status, 'team': choice(body.get('team', 'import_officer'), TEAMS, 'responsible team'), 'assignment_review': False, 'at': time.time(), **{k: text(body.get(k, ''), k) for k in ('responsible', 'blocker', 'next_action', 'source')}}
                if key == 'reported_blocker' and not data['followups'][key]['next_action']:
                    data['followups'].pop(key)
            elif operation == 'coordination':
                update_coordination(data, body.get('item_id'), body.get('item', {}))
                if data['completed'] and holds(data, 'completion'):
                    raise ApiError(422, 'Unmark Completed before adding an unresolved completion hold.')
        # BL is a lookup aid, never a merge key. Explicit acknowledgement keeps separate jobs.
        duplicates = [r for r in all_jobs if r['id'] != identifier and r['client_id'] == record['client_id'] and r['bl'].casefold() == data['bl'].casefold()]
        if duplicates and (operation == 'create' or (before and before['bl'] != data['bl'])) and not text(body.get('duplicate_reason', ''), 'Duplicate BL reason'):
            raise ApiError(409, 'This client / BL already identifies another job. Supply duplicate_reason to create a distinct job.')
        con.execute('INSERT INTO job_updates VALUES(?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET revision=excluded.revision,data=excluded.data', (identifier, revision+1, encode(data)))
        app.store.audit(con, 'shipment_'+operation, {'shipment_id': identifier, 'reason': reason, 'exception_reason': exception,
                         'duplicate_reason': body.get('duplicate_reason', ''), 'before': before, 'after': data,
                         'event': events[-1] if operation == 'movement' else None, 'revision': revision+1})
        result = {'shipment': next(r for r in records(con) if r['id'] == identifier)}
        con.execute('INSERT INTO commands VALUES(?,?,?)', (token, fingerprint, encode(result)))
        return result


def register(route, ApiError):
    @route('POST', '/api/shipments')
    def create(req, query, body):
        return execute(req.app, 'create', body)

    for path, operation in (('update', 'update'), ('movements', 'movement'), ('followups', 'followup'), ('coordination', 'coordination')):
        def register_action(path, operation):
            @route('POST', '/api/shipments/<id>/'+path)
            def action(req, query, body):
                identifier = req.path_params['id']
                if not identifier.isdigit():
                    raise ApiError(400, 'Invalid shipment ID.')
                return execute(req.app, operation, body, int(identifier))
        register_action(path, operation)
