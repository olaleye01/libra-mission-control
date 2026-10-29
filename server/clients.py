"""Owner-managed client identities and department assignments."""
import hashlib
import json
import re
import sqlite3
import time

from core import ApiError
from store import encode
from client_scope import positive_id, scope


def name_value(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[\w &'().-]{2,60}", value.strip()):
        raise ApiError(400, label+' must contain 2–60 letters, numbers or ordinary punctuation.')
    return value.strip()


def text_value(value, label, limit):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ApiError(400, label+' must be text of at most '+str(limit)+' characters.')
    return value.strip()


def keys(body, allowed):
    if not isinstance(body, dict) or set(body)-set(allowed):
        raise ApiError(400, 'Unknown or invalid client/department fields.')


def client_row(con, identifier):
    row = con.execute('''SELECT c.*,d.name AS department_name,(SELECT COUNT(*) FROM shipments s
        WHERE s.client_id=c.id AND NOT EXISTS(SELECT 1 FROM shipment_aliases a WHERE a.shipment_id=s.id)) AS shipment_count
        FROM clients c LEFT JOIN departments d ON d.id=c.department_id WHERE c.id=?''', (identifier,)).fetchone()
    if not row:
        raise ApiError(404, 'Client not found.')
    return dict(row, hidden=bool(row['hidden']))


def department_id(con, value):
    if type(value) is not int or value < 1 or not con.execute('SELECT 1 FROM departments WHERE id=?', (value,)).fetchone():
        raise ApiError(400, 'Select an existing department.')
    return value


def change(app, operation, body, identifier=None):
    allowed = {'create_client': ('name','department_id','notes','command_id','reason'),
               'create_department': ('name','command_id','reason'),
               'update_client': ('revision','changes','command_id','reason')}
    keys(body, allowed[operation])
    command = body.get('command_id')
    if operation == 'update_client' or command is not None:
        if not isinstance(command, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', command):
            raise ApiError(400, 'Supply a unique command_id of 16–100 safe characters.')
    reason = text_value(body.get('reason', 'Owner created client' if operation=='create_client' else 'Owner created department' if operation=='create_department' else ''), 'Reason', 500)
    if not reason:
        raise ApiError(400, 'A reason is required.')
    fingerprint = hashlib.sha256(encode({'operation':operation,'id':identifier,'body':body}).encode()).hexdigest()
    try:
        with app.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            cached = con.execute('SELECT * FROM commands WHERE id=?', (command,)).fetchone() if command else None
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise ApiError(409, 'Command ID already used with different content.')
                return json.loads(cached['response'])
            if operation == 'create_department':
                name = name_value(body.get('name'), 'Department name')
                identifier = con.execute('INSERT INTO departments(name,created_at) VALUES(?,?)', (name,time.time())).lastrowid
                result = {'department':{'id':identifier,'name':name,'client_count':0}}
                app.store.audit(con, 'department_created', {'department_id':identifier,'name':name,'reason':reason})
            elif operation == 'create_client':
                name = name_value(body.get('name'), 'Client name')
                default = con.execute("SELECT id FROM departments WHERE name='FMCG 1'").fetchone()[0]
                department = department_id(con, body.get('department_id', default))
                notes = text_value(body.get('notes',''), 'Notes', 2000)
                # A display name is not authority to reuse another client's reviewed mapping.
                identifier = con.execute('INSERT INTO clients(name,department_id,notes,created_at) VALUES(?,?,?,?)', (name,department,notes,time.time())).lastrowid
                result = {'client':client_row(con,identifier)}
                app.store.audit(con, 'client_created', {'id':identifier,'client_id':identifier,'after':result['client'],'reason':reason})
            else:
                before = client_row(con,identifier)
                if type(body.get('revision')) is not int or body['revision'] != before['revision']:
                    raise ApiError(409, 'Client changed. Reload it before saving.')
                changes = body.get('changes')
                keys(changes, ('name','department_id','hidden','notes'))
                after = dict(before)
                if 'name' in changes:
                    after['name'] = name_value(changes['name'], 'Client name')
                if 'department_id' in changes:
                    after['department_id'] = department_id(con, changes['department_id'])
                if 'hidden' in changes:
                    if type(changes['hidden']) is not bool:
                        raise ApiError(400, 'Hidden must be true or false.')
                    after['hidden'] = changes['hidden']
                if 'notes' in changes:
                    after['notes'] = text_value(changes['notes'], 'Notes', 2000)
                con.execute('UPDATE clients SET name=?,department_id=?,hidden=?,notes=?,revision=revision+1 WHERE id=?',
                            (after['name'],after['department_id'],int(after['hidden']),after['notes'],identifier))
                result = {'client':client_row(con,identifier)}
                app.store.audit(con, 'client_updated', {'client_id':identifier,'before':before,'after':result['client'],'reason':reason})
            if command:
                con.execute('INSERT INTO commands VALUES(?,?,?)', (command,fingerprint,encode(result)))
            return result
    except sqlite3.IntegrityError:
        raise ApiError(409, 'A client or department with this name already exists.')


def register(route, ApiError):
    @route('GET', '/api/departments')
    def departments(req, query, body):
        with req.app.store.connect() as con:
            rows = con.execute('SELECT d.id,d.name,COUNT(c.id) AS client_count FROM departments d LEFT JOIN clients c ON c.department_id=d.id GROUP BY d.id ORDER BY d.id').fetchall()
        return {'departments':[dict(r) for r in rows]}

    @route('POST', '/api/departments')
    def create_department(req, query, body):
        return change(req.app,'create_department',body)

    @route('GET', '/api/clients')
    def listing(req, query, body):
        selection = scope(query)
        with req.app.store.connect() as con:
            clients = [client_row(con,r[0]) for r in con.execute('SELECT id FROM clients ORDER BY id')]
        clients = [c for c in clients if (selection['include_hidden'] or not c['hidden'])
                   and (selection['department_id'] is None or c['department_id']==selection['department_id'])
                   and (selection['client_id'] is None or c['id']==selection['client_id'])]
        return {'clients':clients}

    @route('POST', '/api/clients')
    def create(req, query, body):
        return change(req.app,'create_client',body)

    @route('POST', '/api/clients/<id>/update')
    def update(req, query, body):
        identifier = positive_id(req.path_params['id'], 'client ID')
        return change(req.app,'update_client',body,identifier)
