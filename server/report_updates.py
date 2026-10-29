"""Reviewed report revisions keep job IDs and immutable CSV evidence separate."""
import copy
import hashlib
import json
import re
import time
from collections import Counter

from core import ApiError
from client_scope import active_client
from store import encode
from records import records
from workflow import initial, DATE_KEYS, TEXT_FIELDS
from operations import text, keys, validate


def identity(bl):
    # Punctuation can distinguish real BLs; only case and surrounding space are ignored.
    return bl.strip().casefold()


def merge_source(old, incoming):
    merged = copy.deepcopy(incoming)
    for key in ('bl', 'description', 'terminal', 'liner', 'handler', 'sgd', 'container_count', 'container_size', 'comments'):
        if incoming.get(key) in ('', None):
            merged[key] = old.get(key)
    merged['dates'] = {**old.get('dates', {}), **{k: v for k, v in incoming['dates'].items() if v}}
    d = merged['dates']
    partial = bool(re.search(r'\b(ongoing|awaiting offloading|offloading ongoing|bal\b|balance|remaining|pending.*container)', merged.get('comments') or '', re.I))
    merged['proposed_state'] = ('Delivered' if (d.get('warehouse') or d.get('ecd')) and not partial else
                                'In delivery' if d.get('gate_out') or partial else
                                'In clearing' if d.get('berth') else 'Awaiting arrival')
    return merged


def overlay(job, merged):
    """Three-way comparison updates source-seeded values, preserving independent owner edits."""
    old, new = initial(job['effective_source']), initial(merged)
    data = copy.deepcopy(job['operation'])
    changes, kept = {}, []
    for key in (*TEXT_FIELDS, 'container_count', 'awaiting_duty_receipt'):
        if old.get(key) == new.get(key):
            continue
        if data.get(key) == old.get(key):
            changes[key] = {'before': data.get(key), 'after': new.get(key)}
            data[key] = new.get(key)
        elif data.get(key) != new.get(key):
            kept.append(key)
    for key in DATE_KEYS:
        if old['dates'][key] == new['dates'][key]:
            continue
        if data['dates'][key] == old['dates'][key]:
            changes['dates.'+key] = {'before': data['dates'][key], 'after': new['dates'][key]}
            data['dates'][key] = new['dates'][key]
        elif data['dates'][key] != new['dates'][key]:
            kept.append('dates.'+key)
    return data, changes, kept


def plan(con, batch_id):
    batch = con.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
    if not batch:
        raise ApiError(404, 'Import not found.')
    client = con.execute('SELECT revision,department_id,name FROM clients WHERE id=?', (batch['client_id'],)).fetchone()
    incoming = [json.loads(r[0]) for r in con.execute('SELECT record FROM import_rows WHERE batch_id=? ORDER BY source_row', (batch_id,))]
    jobs = records(con, batch['client_id'])
    source_counts = Counter(identity(r['bl']) for r in incoming)
    linked = {r['source_row']: r['shipment_id'] for r in con.execute('SELECT * FROM report_updates WHERE batch_id=?', (batch_id,))}
    own = {j['source_row']: j for j in jobs if j['batch_id'] == batch_id}
    grouped = {}
    for job in jobs:
        if job['batch_id'] != batch_id and job['id'] not in linked.values():
            grouped.setdefault(identity(job['bl']), []).append(job)
    rows = []
    for source in incoming:
        row = {'source_row': source['source_row'], 'bl': source['bl'], 'action': 'create',
               'shipment_id': None, 'duplicate_id': None, 'changes': {}, 'kept_fields': [], 'note': ''}
        previous = own.get(source['source_row'])
        candidates = grouped.get(identity(source['bl']), [])
        if source['source_row'] in linked:
            row.update(action='unchanged', shipment_id=linked[source['source_row']], note='This report row is already linked to the job.')
        elif not candidates:
            if previous:
                row.update(action='unchanged', shipment_id=previous['id'], note='Existing job from this report; retained.')
        elif len(candidates) != 1 or source_counts[identity(source['bl'])] != 1:
            row.update(action='review', note='Repeated BL: a unique job/report-row match is required. No merge or new duplicate will be created.')
        else:
            job = candidates[0]
            row['shipment_id'] = job['id']
            row['revision'] = job['revision']
            latest = job['report_history'][-1] if job['report_history'] else {'batch_id': job['batch_id'], 'report_date': job['report_date']}
            latest_batch = con.execute('SELECT created_at FROM batches WHERE id=?', (latest['batch_id'],)).fetchone()
            if (job['report_date'] and batch['report_date'] and batch['report_date'] < job['report_date']) or (latest_batch and latest_batch[0] > batch['created_at']):
                row.update(action='review', note='A newer report is already attached to the existing job; this older report will not replace it.')
            elif previous and (previous['revision'] or previous['movements'] or previous['report_history']):
                row.update(action='review', note='The duplicate job has its own edits or history. Review it manually before linking identities.')
            else:
                merged = merge_source(job['effective_source'], source)
                data, changes, kept = overlay(job, merged)
                row.update(action='update', duplicate_id=previous['id'] if previous else None,
                           changes=changes, kept_fields=kept,
                           note='Keep the existing job ID; blank, missing and uninterpretable values do not erase known information.')
                if job['operation']['reconciled'] or job['movements'] or job['operation']['completed']:
                    try:
                        validate({**job, **merged}, data, job['movements'], '')
                    except ApiError as exc:
                        row.update(action='review', note='Operational validation needs review: '+str(exc))
        rows.append(row)
    result = {'batch_id': batch_id, 'status': batch['status'], 'client_id': batch['client_id'], 'rows': rows,
              'client_revision': client['revision'], 'department_id': client['department_id'], 'client_name': client['name'],
              'counts': {key: sum(r['action'] == key for r in rows) for key in ('create', 'update', 'unchanged', 'review')},
              'duplicates_to_archive': sum(r['action'] == 'update' and r['duplicate_id'] is not None for r in rows)}
    result['token'] = hashlib.sha256(encode(result).encode()).hexdigest()
    return result


def apply_review(app, batch_id, body):
    keys(body, ('confirm_test_import', 'plan_token', 'command_id', 'reason'), 'report update')
    if body.get('confirm_test_import') is not True:
        raise ApiError(400, 'Confirm the reviewed test import.')
    reason = text(body.get('reason', ''), 'Review reason')
    if not reason:
        raise ApiError(400, 'A review reason is required.')
    command = text(body.get('command_id', ''), 'Command ID', 100)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', command):
        raise ApiError(400, 'Supply a unique command_id of 16–100 safe characters.')
    fingerprint = hashlib.sha256(encode({'report': batch_id, 'body': body}).encode()).hexdigest()
    with app.store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        cached = con.execute('SELECT * FROM commands WHERE id=?', (command,)).fetchone()
        if cached:
            if cached['fingerprint'] != fingerprint:
                raise ApiError(409, 'Command ID already used with different content.')
            return json.loads(cached['response'])
        reviewed = plan(con, batch_id)
        active_client(con, reviewed['client_id'])
        if body.get('plan_token') != reviewed['token']:
            raise ApiError(409, 'The register or report changed. Reopen the report update review.')
        if reviewed['counts']['review']:
            raise ApiError(409, 'Some BLs need manual review. No records were changed.')
        jobs = {j['id']: j for j in records(con, reviewed['client_id'])}
        for row in reviewed['rows']:
            if row['action'] == 'unchanged':
                continue
            source = json.loads(con.execute('SELECT record FROM import_rows WHERE batch_id=? AND source_row=?', (batch_id, row['source_row'])).fetchone()[0])
            if row['action'] == 'create':
                identifier = con.execute('INSERT INTO shipments(client_id,batch_id,source_row,created_at) VALUES(?,?,?,?)',
                                         (reviewed['client_id'], batch_id, row['source_row'], time.time())).lastrowid
                app.store.audit(con, 'report_job_created', {'shipment_id': identifier, 'batch_id': batch_id, 'source_row': row['source_row'], 'reason': reason})
                continue
            job = jobs[row['shipment_id']]
            merged = merge_source(job['effective_source'], source)
            data, _, _ = overlay(job, merged)
            con.execute('INSERT INTO report_updates(shipment_id,batch_id,source_row,effective_record,created_at) VALUES(?,?,?,?,?)',
                        (job['id'], batch_id, row['source_row'], encode(merged), time.time()))
            con.execute('INSERT INTO job_updates VALUES(?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET revision=excluded.revision,data=excluded.data',
                        (job['id'], job['revision']+1, encode(data)))
            if row['duplicate_id']:
                # Keep the old row and its source; exclude this reviewed duplicate from active counts.
                con.execute('INSERT INTO shipment_aliases VALUES(?,?,?,?)', (row['duplicate_id'], job['id'], reason, time.time()))
            app.store.audit(con, 'report_job_updated', {'shipment_id': job['id'], 'batch_id': batch_id,
                            'source_row': row['source_row'], 'duplicate_id': row['duplicate_id'], 'reason': reason,
                            'before': job['operation'], 'after': data, 'kept_fields': row['kept_fields']})
        con.execute("UPDATE batches SET status='applied' WHERE id=?", (batch_id,))
        result = {'batch_id': batch_id, 'status': 'applied', 'counts': reviewed['counts'],
                  'duplicates_archived': reviewed['duplicates_to_archive'], 'mode': 'test'}
        con.execute('INSERT INTO commands VALUES(?,?,?)', (command, fingerprint, encode(result)))
        return result


def register(route, ApiError):
    @route('GET', '/api/imports/<id>/review-updates')
    def review(req, query, body):
        with req.app.store.connect() as con:
            return {'review': plan(con, req.path_params['id'])}

    @route('POST', '/api/imports/<id>/review-updates')
    def apply(req, query, body):
        return apply_review(req.app, req.path_params['id'], body)
