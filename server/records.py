"""Join immutable imports with independently versioned operational records."""
import json
from workflow import initial, derive


def records(con, client_id=None, as_of=None):
    sql = """SELECT s.id,s.client_id,s.batch_id,s.source_row,c.name AS client_name,
        b.filename,b.report_date,r.record,u.data,u.revision FROM shipments s
        JOIN clients c ON c.id=s.client_id LEFT JOIN batches b ON b.id=s.batch_id
        LEFT JOIN import_rows r ON r.batch_id=s.batch_id AND r.source_row=s.source_row
        LEFT JOIN job_updates u ON u.shipment_id=s.id"""
    rows = con.execute(sql + (' WHERE s.client_id=?' if client_id else '') + ' ORDER BY s.created_at DESC,s.id DESC', (client_id,) if client_id else ()).fetchall()
    movements = {}
    for event in con.execute('SELECT * FROM movements ORDER BY created_at,id'):
        movements.setdefault(event['shipment_id'], []).append(dict(event))
    result = []
    for row in rows:
        r = dict(row)
        raw_record = r.pop('record')
        data = r.pop('data')
        if raw_record:
            r.update(json.loads(raw_record))
        else:
            r.update(raw=[], dates={}, issues=[], comments='', section='Manual entry', proposed_state='Awaiting arrival', evidence='Owner recorded · not independently verified')
        r.update(job_id='LMC-{:05d}'.format(r['id']), revision=r['revision'] or 0)
        r['source_snapshot'] = json.loads(raw_record) if raw_record else None
        data = json.loads(data) if data else initial(r)
        result.append(derive(r, data, movements.get(r['id'], []), bool(row['data']), as_of))
    return result
