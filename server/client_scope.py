"""Client visibility is workspace organisation, never an access permission."""
from core import ApiError


def positive_id(value, label):
    if value in (None, ''):
        return None
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ApiError(400, 'Invalid '+label+'.')
    return int(value)


def scope(query):
    hidden = query.get('include_hidden', '0')
    if hidden not in ('0', '1'):
        raise ApiError(400, 'include_hidden must be 0 or 1.')
    return {'department_id': positive_id(query.get('department_id'), 'department filter'),
            'client_id': positive_id(query.get('client_id'), 'client filter'), 'include_hidden': hidden == '1'}


def filtered(rows, query):
    selection = scope(query)
    return [r for r in rows if (selection['include_hidden'] or not r['client_hidden'])
            and (selection['department_id'] is None or r['department_id'] == selection['department_id'])
            and (selection['client_id'] is None or r['client_id'] == selection['client_id'])]


def active_client(con, identifier):
    client = con.execute('SELECT * FROM clients WHERE id=?', (identifier,)).fetchone()
    if not client:
        raise ApiError(404, 'Client not found.')
    if client['hidden']:
        raise ApiError(409, 'This client is hidden. Restore it in Clients & departments before creating jobs or applying reports.')
    return client
