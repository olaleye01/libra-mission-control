"""People, manual assignments and queues. These labels do not grant permissions."""
import copy

TEAMS = {'import_officer': 'Import Officer', 'field_agent': 'Field Agent',
         'accounts': 'Accounts', 'qac': 'QAC', 'regulatory': 'Regulatory', 'unassigned': 'Unassigned'}
STATUSES = {'open': 'Open', 'in_progress': 'In progress', 'awaiting_response': 'Awaiting response', 'resolved': 'Resolved'}
QUEUES = {'my_next': 'My next actions', 'awaiting_response': 'Awaiting responses',
          'clearing_blockers': 'Clearing blockers', 'delivery': 'Delivery progress', 'closure': 'Closure'}
CATEGORIES = ('clearing', 'delivery', 'closure', 'regulatory')
BLOCK_STEPS = {'': 'No process hold', 'tdo': 'TDO', 'gate_out': 'Gate-out', 'warehouse': 'Warehouse arrival', 'completion': 'Completion'}


def normalize(data):
    """Interpret old role fields without writing imports, history or stored JSON on reads."""
    data = copy.deepcopy(data)
    if data.get('ownership_version') != 1:
        old_handler, old_agent = data.get('handler', ''), data.get('field_agent', '')
        data['legacy_handler'] = old_handler if old_agent and old_handler and old_agent != old_handler else ''
        data['field_agent'] = old_agent or old_handler
        data['handler'] = data['field_agent']  # Compatibility alias, not a second job role.
        data['import_officer'] = data.get('import_officer') or 'Owner'
        data['ownership_version'] = 1
    data.setdefault('delivery_location', '')
    data['dates'].setdefault('discharge', None)
    data.setdefault('arrival_basis', 'legacy_berth')
    data.setdefault('coordination', {})
    for item in data['followups'].values():
        if 'team' not in item:
            # Preserve explicitly saved assignments; the old automatic handler fallback was not a saved assignment.
            item['team'] = 'unassigned' if item.get('responsible') else 'import_officer'
            item['assignment_review'] = bool(item.get('responsible'))
    return data


def responsible(data, team, person=''):
    if person:
        return person
    return {'import_officer': data['import_officer'], 'field_agent': data['field_agent']}.get(team) or 'Unassigned'


def holds(data, step):
    return [item for item in data['coordination'].values() if item['status'] != 'resolved' and item['blocks_step'] == step]


def action(item, data, kind='calculated'):
    item = copy.deepcopy(item)
    team = item.get('team', 'import_officer')
    item.update(team=team, team_label=TEAMS[team], responsible=responsible(data, team, item.get('responsible', '')),
                import_officer=data['import_officer'], field_agent=data['field_agent'], reminder_recipient='Owner',
                kind=kind, queues=[])
    if item['status'] == 'resolved':
        return item
    if team == 'import_officer' and item['status'] in ('open', 'in_progress'):
        item['queues'].append('my_next')
    if item['status'] == 'awaiting_response':
        item['queues'].append('awaiting_response')
    if item.get('blocker') or item.get('blocks_step') or item['key'] == 'tdo_age':
        item['queues'].append('clearing_blockers')
    category = item.get('category')
    if category == 'delivery' or item['key'] == 'delivery_progress':
        item['queues'].append('delivery')
    if category == 'closure' or item['key'] in ('ecd', 'closure'):
        item['queues'].append('closure')
    return item


def counts(items):
    return {key: sum(key in item['queues'] for item in items) for key in QUEUES}
