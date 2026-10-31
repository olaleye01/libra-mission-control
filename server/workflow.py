"""Deterministic clearing rules. Source snapshots and owner reports stay distinct."""
import copy
import datetime as dt
import re
from zoneinfo import ZoneInfo

from imports import DATE_FIELDS
from coordination import normalize, action, holds

INVOICE_KEYS = ('shipping', 'additional', 'terminal')
CLOSURE_KEYS = ('empty_returns', 'shipping_final')
TEXT_FIELDS = ('bl', 'description', 'terminal', 'liner', 'handler', 'field_agent', 'import_officer', 'sgd', 'container_size', 'delivery_location')
# draft_received remains a legacy date so older entries and audit history survive.
DATE_KEYS = tuple(k for k in DATE_FIELDS if k not in ('gate_out', 'warehouse')) + ('draft_received', 'draft_approved', 'client_invoiced', 'discharge')
ACTION_KEYS = ('shipping_invoice', 'rotation', 'paar', 'obl', 'draft', 'draft_approval', 'final_assessment', 'assessment_details', 'duty_receipt', 'terminal_invoice', 'tdo_age', 'ecd', 'closure', 'reported_blocker', 'additional_invoice', 'shipping_payment', 'additional_payment', 'terminal_payment', 'delivery_progress')


def today():
    return dt.datetime.now(ZoneInfo('Africa/Lagos')).date().isoformat()


def initial(record, manual=False):
    data = {k: record.get(k, '') for k in TEXT_FIELDS}
    data.update(container_count=record.get('container_count'), dates={k: record.get('dates', {}).get(k) for k in DATE_KEYS},
                reconciled=manual, awaiting_duty_receipt=bool(re.search(r'awaiting\s+(?:the\s+)?duty\s+receipt', record.get('comments', ''), re.I)),
                approval_by='', rotation={'status': 'unknown', 'number': ''},
                invoices={k: {'request': 'unknown', 'received': None, 'payment': 'unknown', 'payment_date': None,
                              'rated_through': None, 'coverage': k, 'applicability': 'unknown', 'reason': ''} for k in INVOICE_KEYS},
                closure={k: {'applicability': 'unknown', 'date': None, 'reason': ''} for k in CLOSURE_KEYS},
                completed=False, followups={})
    return normalize(data)


def active_events(events):
    superseded = {e['supersedes'] for e in events if e['supersedes']}
    return [e for e in events if e['id'] not in superseded and e['quantity'] > 0]


def movement_problems(data, events):
    """Revalidate all active events after a correction, including earlier dependants."""
    active = active_events(events)
    problems = []
    total = data['container_count']
    d = data['dates']
    coverage = data.get('release_coverage', {})
    for kind in ('gate_out', 'warehouse'):
        count = sum(e['quantity'] for e in active if e['kind'] == kind)
        if count and (total is None or count > total):
            problems.append('Movement totals require a known container total and cannot exceed it.')
    for e in active:
        if e['kind'] == 'gate_out':
            cumulative = sum(x['quantity'] for x in active if x['kind'] == 'gate_out' and x['date'] <= e['date'])
            for key in ('do', 'tdo', 'customs_release'):
                if not d[key] or d[key] > e['date'] or (coverage.get(key) or 0) < cumulative:
                    problems.append('Gate-out needs dated DO, TDO and Customs release covering the cumulative count.')
                    break
        else:
            arrived = sum(x['quantity'] for x in active if x['kind'] == 'warehouse' and x['date'] <= e['date'])
            gated = sum(x['quantity'] for x in active if x['kind'] == 'gate_out' and x['date'] <= e['date'])
            if arrived > gated:
                problems.append('Warehouse arrival exceeds gate-out accounted for by that date.')
    return list(dict.fromkeys(problems))


def derive(record, data, events, operational=False, as_of=None):
    data = normalize(data)
    r = copy.deepcopy(record)
    r.update({k: data[k] for k in TEXT_FIELDS})
    r.update(container_count=data['container_count'], operational=operational, operation=copy.deepcopy(data), movements=events)
    r['dates'] = {**record.get('dates', {}), **data['dates']}
    source = record.get('current_source_snapshot') or record.get('source_snapshot')
    r['issues'] = copy.deepcopy(source.get('issues', []) if source is not None else record.get('issues', []) if 'operational' not in record else [])
    for i in r['issues']:
        i['source'] = 'Original import'
    if data.get('legacy_handler'):
        r['issues'].append({'code': 'ownership_review', 'severity': 'warning', 'field': 'field_agent', 'message': 'Earlier File Handler and Field Agent entries differ. Field Agent retained; earlier handler remains available for review: '+data['legacy_handler'], 'source': 'Owner record'})
    for item in data['coordination'].values():
        if item['status'] != 'resolved' and item['blocks_step']:
            r['issues'].append({'code': 'manual_hold', 'severity': 'warning', 'field': item['blocks_step'], 'message': 'Owner-recorded hold: '+item['title'], 'source': item['source']})
    active = active_events(events)
    gated = sum(e['quantity'] for e in active if e['kind'] == 'gate_out')
    delivered = sum(e['quantity'] for e in active if e['kind'] == 'warehouse')
    total = data['container_count']
    reconciled = data['reconciled'] and total is not None
    r.update(gate_out_count=gated if reconciled else None, delivered_count=delivered if reconciled else None,
             pending_count=total-delivered if reconciled else None)
    if reconciled:
        for kind in ('gate_out', 'warehouse'):
            dates = [e['date'] for e in active if e['kind'] == kind]
            r['dates'][kind] = max(dates) if dates else None
    problems = movement_problems(data, events)
    d = data['dates']
    if d['tdo'] and (not d['do'] or d['do'] > d['tdo']):
        problems.append('TDO is reported without a preceding DO date.')
    coverage = data.get('release_coverage', {})
    if (coverage.get('tdo') or 0) > (coverage.get('do') or 0):
        problems.append('TDO coverage exceeds confirmed DO coverage.')
    for message in dict.fromkeys(problems):
        r['issues'].append({'code': 'operational_release_review', 'severity': 'warning', 'field': 'movements', 'message': message, 'source': 'Owner update'})
    pair = bool(d['assessment'] and data['sgd'])
    r['assessment'] = {'draft_requirements_cleared': pair, 'clearance_reason': 'Final assessment received date and C Number recorded.' if pair else None,
                       'final_received_reported': bool(d['assessment'] or data['awaiting_duty_receipt']),
                       'approval_date': d['draft_approved'], 'approval_by': data['approval_by']}
    if data['awaiting_duty_receipt'] and not pair:
        r['issues'].append({'code': 'assessment_completeness', 'severity': 'warning', 'field': 'assessment', 'message': 'Final assessment reported received; supply missing final receipt date / C Number.', 'source': 'Owner report'})
    if pair and re.search(r'(?:awaiting|pending|request).*draft', record.get('comments', ''), re.I):
        r['issues'].append({'code': 'draft_comment_conflict', 'severity': 'warning', 'field': 'comments', 'message': 'Original draft-stage request conflicts with the final-assessment date and C Number. Original retained.', 'source': 'Original import'})
    closure_missing = []
    if not reconciled or total != delivered:
        closure_missing.append('All containers reconciled at warehouse')
    if not d['ecd']:
        closure_missing.append('ECD received')
    if not d['client_invoiced']:
        closure_missing.append('Client invoicing')
    for key, label in (('empty_returns', 'Empty-container returns'), ('shipping_final', 'Shipping-line final invoice')):
        item = data['closure'][key]
        if item['applicability'] == 'unknown' or (item['applicability'] == 'required' and not item['date']):
            closure_missing.append(label)
    if holds(data, 'completion'):
        closure_missing.append('Owner-recorded completion hold resolved')
    if problems:
        closure_missing.append('Movement/release exceptions reconciled')
    r['closure_missing'] = closure_missing
    # Old report berth dates retain their meaning; reviewed carrier arrivals use discharge.
    arrived = d.get('discharge') if data['arrival_basis'] == 'discharge' else d.get('discharge') or d['berth']
    if operational and data['reconciled']:
        r['state'] = ('Completed' if data['completed'] and not closure_missing else 'Delivered' if reconciled and delivered == total else 'In delivery' if gated or delivered else 'In clearing' if arrived else 'Awaiting arrival')
        r['review_status'] = 'Owner recorded · test'
        r['state_note'] = 'Owner-recorded progress; quantities reconciled by count, without independent verification.'
    else:
        r['state'] = record.get('proposed_state', 'Awaiting arrival')
        r['review_status'] = 'Historical proposal' if record.get('batch_id') else 'Owner recorded · count unknown'
        r['state_note'] = 'Historical stage retained until the owner reconciles the container total and movement history.' if record.get('batch_id') else 'Record a container total to reconcile delivery progress.'
    r['actions'] = actions(r, data, as_of or (today() if data['reconciled'] else r.get('report_date')))
    return r


def actions(r, data, as_of):
    result = []
    d = data['dates']
    followups = data['followups']

    def add(key, text):
        if any(a['key'] == key for a in result):
            return
        f = followups.get(key, {})
        result.append({'key': key, 'next_action': f.get('next_action') or text, 'status': f.get('status', 'open'),
                       'responsible': f.get('responsible', ''), 'team': f.get('team', 'import_officer'),
                       'assignment_review': f.get('assignment_review', False), 'blocker': f.get('blocker', ''),
                       'source': f.get('source') or ('Owner record' if r['operational'] else 'Historical import'),
                       'last_action_at': f.get('at'), 'as_of': as_of})

    combined = any(v['coverage'] == 'combined' and v['received'] for v in data['invoices'].values())
    def invoice_received(key):
        v = data['invoices'][key]
        return combined or v['received'] or v['applicability'] == 'not_applicable'

    if as_of and d['eta'] and not d['berth'] and dt.date.fromisoformat(as_of) >= dt.date.fromisoformat(d['eta']) - dt.timedelta(days=5):
        if not invoice_received('shipping'):
            add('shipping_invoice', 'Confirm / obtain shipping invoice')
        if data['rotation']['status'] != 'gotten':
            add('rotation', 'Confirm / obtain rotation number')
        for key in ('paar', 'obl'):
            if not d[key]:
                add(key, 'Confirm / obtain '+key.upper())
    pair = r['assessment']['draft_requirements_cleared']
    if d['paar'] and not pair:
        if not d['draft_approved']:
            add('draft_approval', 'Obtain client approval to proceed with final assessment')
        elif not d['assessment']:
            add('final_assessment', 'Obtain final assessment')
    if data['awaiting_duty_receipt'] and not pair:
        add('assessment_details', 'Complete final-assessment receipt date / C Number')
    if (d['assessment'] or data['awaiting_duty_receipt']) and not d['duty_receipt']:
        add('duty_receipt', 'Follow up duty receipt; payment remains separately reported')
    if d['duty_receipt'] and not invoice_received('terminal'):
        add('terminal_invoice', 'Confirm / obtain terminal invoice')
    if as_of and d['berth'] and not d['tdo']:
        age = (dt.date.fromisoformat(as_of)-dt.date.fromisoformat(d['berth'])).days
        if age > 5:
            add('tdo_age', str(age)+' days since berthing: confirm TDO status and what is holding the job')
    for key, item in data['invoices'].items():
        if item['request'] == 'requested' and not invoice_received(key):
            add(key+'_invoice' if key != 'shipping' else 'shipping_invoice', 'Await '+key+' invoice response')
        if item['payment'] == 'not_paid' and item['applicability'] != 'not_applicable':
            add(key+'_payment', 'Follow up '+key+' invoice payment (owner-reported not paid)')
    if r['state'] in ('Delivered', 'Completed') and not d['ecd']:
        arrival_dates = {e['date'] for e in active_events(r['movements']) if e['kind'] == 'warehouse'}
        if len(arrival_dates) != 1 or not as_of:
            add('ecd', 'Confirm ECD follow-up anchor: split delivery or delivery date unresolved')
        elif (dt.date.fromisoformat(as_of)-dt.date.fromisoformat(next(iter(arrival_dates)))).days >= 7:
            add('ecd', 'Follow up Exchange Control Documents (seven days after warehouse delivery)')
    if r['state'] == 'In delivery' and r['pending_count']:
        add('delivery_progress', 'Confirm warehouse delivery of '+str(r['pending_count'])+' pending containers')
    if r['state'] == 'Delivered':
        add('closure', 'Review administrative closure: '+', '.join(r['closure_missing']) if r['closure_missing'] else 'Confirm completion of this job')
    if followups.get('reported_blocker', {}).get('next_action'):
        add('reported_blocker', 'Review reported blocker')
    result = [action(item, data) for item in result]
    for item in data['coordination'].values():
        result.append(action({**item, 'key': item['id'], 'item_id': item['id'],
                              'last_action_at': item['updated_at'], 'as_of': as_of}, data, 'coordination'))
    return result
