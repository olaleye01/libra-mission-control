"""Join immutable imports with independently versioned operational records."""
import json
from workflow import initial, derive
from coordination import normalize


def records(con, client_id=None, as_of=None):
    sql = """SELECT s.id,s.client_id,s.batch_id,s.source_row,c.name AS client_name,
        c.department_id,d.name AS department_name,c.hidden AS client_hidden,
        b.filename,b.report_date,r.record,u.data,u.revision FROM shipments s
        JOIN clients c ON c.id=s.client_id LEFT JOIN departments d ON d.id=c.department_id
        LEFT JOIN batches b ON b.id=s.batch_id
        LEFT JOIN import_rows r ON r.batch_id=s.batch_id AND r.source_row=s.source_row
        LEFT JOIN job_updates u ON u.shipment_id=s.id"""
    rows = con.execute(sql + ' WHERE NOT EXISTS(SELECT 1 FROM shipment_aliases a WHERE a.shipment_id=s.id)' + (' AND s.client_id=?' if client_id else '') + ' ORDER BY s.created_at DESC,s.id DESC', (client_id,) if client_id else ()).fetchall()
    reports = {}
    for report in con.execute('''SELECT u.*,b.filename,b.report_date,r.record FROM report_updates u
            JOIN batches b ON b.id=u.batch_id JOIN import_rows r ON r.batch_id=u.batch_id AND r.source_row=u.source_row ORDER BY u.id'''):
        reports.setdefault(report['shipment_id'], []).append(dict(report))
    movements = {}
    for event in con.execute('SELECT * FROM movements ORDER BY created_at,id'):
        movements.setdefault(event['shipment_id'], []).append(dict(event))
    result = []
    for row in rows:
        r = dict(row)
        r['client_hidden'] = bool(r['client_hidden'])
        raw_record = r.pop('record')
        data = r.pop('data')
        if raw_record:
            r.update(json.loads(raw_record))
        else:
            r.update(raw=[], dates={}, issues=[], comments='', section='Manual entry', proposed_state='Awaiting arrival', evidence='Owner recorded · not independently verified')
        r.update(job_id='LMC-{:05d}'.format(r['id']), revision=r['revision'] or 0)
        r['original_filename'] = r['filename']
        r['source_snapshot'] = json.loads(raw_record) if raw_record else None
        history = reports.get(r['id'], [])
        r['report_history'] = [{'batch_id': h['batch_id'], 'source_row': h['source_row'], 'filename': h['filename'],
                                'report_date': h['report_date'], 'record': json.loads(h['record'])} for h in history]
        if history:
            # The original import stays immutable; later reports supply a separate effective source.
            r.update(json.loads(history[-1]['effective_record']))
            r['filename'] = history[-1]['filename']
            r['report_date'] = next((h['report_date'] for h in reversed(history) if h['report_date']), r['report_date'])
            r['current_source_snapshot'] = json.loads(history[-1]['record'])
            r['source_row'] = row['source_row']
        r['effective_source'] = json.loads(history[-1]['effective_record']) if history else json.loads(raw_record) if raw_record else {'raw': [], 'dates': {}, 'issues': [], 'comments': '', 'proposed_state': 'Awaiting arrival'}
        data = normalize(json.loads(data)) if data else initial(r)
        result.append(derive(r, data, movements.get(r['id'], []), bool(row['data']), as_of))
    return result
