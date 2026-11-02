"""Shipment-only briefings and ephemeral conversations; no operational write tools."""
import copy
import hashlib
import json
import re
import threading
import time
import uuid
from collections import Counter, OrderedDict

from client_scope import positive_id
from core import ApiError
from imports import STATES
from records import records


SCOPE_KEYS = ('department_id', 'client_id', 'shipment_id')
LIMITATIONS = [
    'Read-only: Jarvis cannot change shipments, make payments or send messages.',
    'Pending source information is not proof that a document is missing.',
    'Historical reports keep their reporting cut-off; unknown dates remain unknown.'
]
DATES = ('eta', 'berth', 'discharge', 'paar', 'obl', 'assessment', 'duty_receipt',
         'customs_release', 'do', 'tdo', 'gate_out', 'warehouse', 'ecd')
PENDING_FIELDS = set(DATES) | {'bl', 'description', 'terminal', 'liner', 'container_count',
                             'container_size', 'field_agent', 'handler', 'sgd', 'rotation',
                             'shipping_invoice', 'terminal_invoice'}
PRIORITY = {'tdo_age': 1, 'duty_receipt': 2, 'delivery_progress': 2, 'ecd': 2,
            'draft_approval': 3, 'final_assessment': 3, 'assessment_details': 3,
            'shipping_invoice': 4, 'rotation': 4, 'paar': 4, 'obl': 4,
            'terminal_invoice': 4, 'closure': 5}
SAFE_ID = re.compile(r'[A-Za-z0-9_-]{16,100}')
MAX_CONTEXT_JOBS = 20
MAX_ACTIONS = 12


def identifier_value(value, label):
    if value not in (None, '') and (len(str(value)) > 19 or (str(value).isdigit() and int(value) > 9223372036854775807)):
        raise ApiError(400, 'Invalid ' + label + '.')
    return positive_id(value, label)


def text(value, limit=700):
    return str(value or '')[:limit]


def scope_key(scope):
    return tuple(scope[key] for key in SCOPE_KEYS)


def historical(job):
    # An unreconciled manual job is not a historical imported proposal.
    return bool(job.get('batch_id')) and not job['operation']['reconciled']


def reference(job, tab='milestones'):
    return {'shipment_id': job['id'], 'job_id': job['job_id'], 'bl': text(job['bl'], 200),
            'client_name': text(job['client_name'], 60), 'tab': tab,
            'label': job['job_id'] + ' · ' + text(job['bl'], 200)}


def action_dto(job, item):
    return {'shipment_id': job['id'], 'job_id': job['job_id'], 'bl': text(job['bl'], 200),
            'client_name': text(job['client_name'], 60), 'key': text(item['key'], 100),
            'next_action': text(item['next_action']), 'status': item['status'],
            'team': item['team'], 'responsible': text(item['responsible'], 100),
            'as_of': item['as_of'], 'historical': historical(job),
            'source': 'Historical report' if historical(job) else 'Owner-recorded job',
            'blocker': text(item.get('blocker')), 'blocks_step': item.get('blocks_step', ''),
            'tab': 'coordination' if item['kind'] == 'coordination' else 'followups'}


def selected_actions(jobs):
    result = []
    for job in jobs:
        for item in job['actions']:
            if item['status'] == 'resolved':
                continue
            priority = 0 if item.get('blocker') or item.get('blocks_step') else PRIORITY.get(item['key'], 6)
            result.append((priority, 'my_next' not in item['queues'], job['id'], item['key'], action_dto(job, item)))
    return [item[-1] for item in sorted(result, key=lambda row: row[:-1])]


def shipment_dto(job):
    """A positive field projection keeps imported money/raw cells out of the assistant boundary."""
    return {'shipment_id': job['id'], 'job_id': job['job_id'], 'bl': text(job['bl'], 200),
            'client_id': job['client_id'], 'client_name': text(job['client_name'], 60),
            'department_id': job['department_id'], 'department_name': text(job['department_name'], 60),
            'state': job['state'], 'historical': historical(job), 'report_date': job.get('report_date'),
            'source': 'Historical report' if historical(job) else 'Owner-recorded job',
            'review_status': job['review_status'], 'container_count': job['container_count'],
            'pending_warehouse_count': job['pending_count'], 'gate_out_count': job['gate_out_count'],
            'delivered_count': job['delivered_count'], 'import_officer': text(job['import_officer'], 100),
            'field_agent': text(job['field_agent'], 100), 'dates': {key: job['dates'].get(key) for key in DATES},
            'pending_source_fields': [key for key in job.get('pending_fields', []) if key in PENDING_FIELDS],
            'record_question_count': sum(i['severity'] == 'warning' for i in job['issues']),
            'actions': selected_actions([job])[:MAX_ACTIONS]}


class Jarvis:
    """One application's bounded memory, always separated by authenticated session and scope."""
    ttl = 30 * 60
    max_conversations = 64
    max_cached_turns = 256
    max_history_messages = 12

    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.conversations = OrderedDict()
        self.turns = OrderedDict()

    def load(self, selection):
        scope = {key: identifier_value(selection.get(key), key.replace('_', ' ')) for key in SCOPE_KEYS}
        with self.app.store.connect() as con:
            con.execute('PRAGMA query_only=ON')
            if scope['department_id'] and not con.execute('SELECT 1 FROM departments WHERE id=?', (scope['department_id'],)).fetchone():
                raise ApiError(404, 'Selected scope is unavailable.')
            client = None
            if scope['client_id']:
                client = con.execute('SELECT name,department_id,hidden FROM clients WHERE id=?', (scope['client_id'],)).fetchone()
                if not client or client['hidden'] or (scope['department_id'] and client['department_id'] != scope['department_id']):
                    raise ApiError(404, 'Selected scope is unavailable.')
            jobs = [job for job in records(con, scope['client_id']) if not job['client_hidden']
                    and (scope['department_id'] is None or job['department_id'] == scope['department_id'])]
            if scope['shipment_id']:
                jobs = [job for job in jobs if job['id'] == scope['shipment_id']]
                if not jobs:
                    raise ApiError(404, 'Shipment is unavailable in the selected scope.')
            department = con.execute('SELECT name FROM departments WHERE id=?', (scope['department_id'],)).fetchone() if scope['department_id'] else None
        scope.update(department_name=department['name'] if department else None,
                     client_name=client['name'] if client else None)
        return scope, jobs

    def provider_status(self):
        provider = getattr(self.app, 'jarvis_provider', None)
        if provider is None:
            return {'enabled': False, 'verified': False, 'reason': 'Hermes shipment-only connection is not verified.'}
        try:
            status = provider.status()
            if not isinstance(status, dict):
                raise ValueError('Invalid status')
            return {'enabled': status.get('enabled') is True, 'verified': status.get('verified') is True,
                    'reason': text(status.get('reason') or 'Hermes connection is unavailable.', 250)}
        except Exception:
            return {'enabled': False, 'verified': False, 'reason': 'Hermes connection status could not be verified.'}

    def envelope(self, scope, jobs):
        actions = selected_actions(jobs)
        states = Counter(job['state'] for job in jobs)
        totals = {'shipments': len(jobs), 'active_shipments': sum(job['state'] != 'Completed' for job in jobs),
                  'pending_actions': len(actions),
                  'officer_actions': sum('my_next' in item['queues'] for job in jobs for item in job['actions']),
                  'shipments_with_actions': len({item['shipment_id'] for item in actions}),
                  'record_questions': sum(any(i['severity'] == 'warning' for i in job['issues']) for job in jobs),
                  'unknown_container_counts': sum(job['container_count'] is None for job in jobs),
                  'states': {state: states[state] for state in STATES}}
        by_id = {job['id']: job for job in jobs}
        refs, seen = [], set()
        for item in actions[:MAX_ACTIONS]:
            if item['shipment_id'] not in seen:
                seen.add(item['shipment_id'])
                refs.append(reference(by_id[item['shipment_id']], item['tab']))
        if not refs:
            refs = [reference(job) for job in jobs[:MAX_CONTEXT_JOBS]]
        status = self.provider_status()
        return {'assistant': 'Jarvis', 'mode': 'local_guided', 'scope': scope, 'totals': totals,
                'actions': actions[:MAX_ACTIONS], 'references': refs, 'limitations': list(LIMITATIONS),
                'capabilities': {'read_only': True, 'voice_input': 'unavailable',
                                 'voice_output': 'unavailable',
                                 'provider_verified': status['enabled'] and status['verified']},
                'connection': status}

    def briefing_text(self, response):
        totals = response['totals']
        if not totals['shipments']:
            return 'There are no visible shipments in this selection.'
        lines = ['{} shipment(s), with {} pending action item(s) across {} job(s).'.format(
            totals['shipments'], totals['pending_actions'], totals['shipments_with_actions'])]
        if not response['actions']:
            lines.append('No calculated or recorded next actions are available. This does not confirm every document has been received.')
        for item in response['actions'][:4]:
            stamp = ('Historical cut-off ' + item['as_of'] if item['historical'] and item['as_of'] else
                     'Historical cut-off not supplied' if item['historical'] else
                     'As of ' + item['as_of'] if item['as_of'] else 'Calculation date unknown')
            lines.append('{} · {}: {}. {}. Owner: {}.'.format(item['job_id'], item['bl'], item['next_action'], stamp, item['responsible']))
        lines.append('Pending information needs confirmation; it is not proof a document is missing.')
        return '\n'.join(lines)

    def briefing(self, selection):
        scope, jobs = self.load(selection)
        result = self.envelope(scope, jobs)
        result['text'] = self.briefing_text(result)
        return result

    def execute_tool(self, name, arguments, scope):
        """Future transports receive data only; this allowlist never accepts SQL, files or write verbs."""
        if name not in ('get_briefing', 'find_shipments', 'get_shipment_pending'):
            raise ApiError(400, 'Jarvis only supports shipment briefing and pending-information tools.')
        if not isinstance(arguments, dict):
            raise ApiError(400, 'Invalid shipment tool arguments.')
        selected, jobs = self.load(scope)
        if name == 'get_briefing':
            if arguments:
                raise ApiError(400, 'Briefing takes no extra arguments.')
            result = self.envelope(selected, jobs)
            result['text'] = self.briefing_text(result)
            return result
        if name == 'get_shipment_pending':
            if set(arguments) != {'shipment_id'}:
                raise ApiError(400, 'Supply only an internal shipment ID.')
            identifier = identifier_value(arguments['shipment_id'], 'shipment ID')
            job = next((job for job in jobs if job['id'] == identifier), None)
            if job is None:
                raise ApiError(404, 'Shipment is unavailable in the selected scope.')
            return {'shipment': shipment_dto(job), 'reference': reference(job)}
        if set(arguments) != {'query'} or not isinstance(arguments.get('query'), str) or not 1 <= len(arguments['query'].strip()) <= 120:
            raise ApiError(400, 'Supply a shipment lookup of 1–120 characters.')
        query = arguments['query'].strip().casefold()
        matches = [job for job in jobs if query in (job['bl'].strip().casefold(), job['job_id'].casefold(), job['client_name'].casefold())]
        return {'shipments': [shipment_dto(job) for job in matches[:MAX_CONTEXT_JOBS]], 'total': len(matches),
                'references': [reference(job) for job in matches[:MAX_CONTEXT_JOBS]]}

    def prune(self, now):
        for key in list(self.conversations):
            if now - self.conversations[key]['at'] >= self.ttl:
                del self.conversations[key]
        for key in list(self.turns):
            if self.turns[key]['conversation_id'] not in self.conversations:
                del self.turns[key]

    def select_message_jobs(self, message, jobs):
        identifiers = {int(value) for value in re.findall(r'\bLMC-0*(\d{1,19})\b', message, re.I)}
        if identifiers:
            selected = [job for job in jobs if job['id'] in identifiers]
            return selected, True
        matches = [job for job in jobs if job['bl'].strip() and re.search(
            r'(?<!\w)' + re.escape(job['bl'].strip()) + r'(?!\w)', message, re.I)]
        if matches:
            return matches, True
        clients = {job['client_name'].casefold() for job in jobs if re.search(
            r'(?<!\w)' + re.escape(job['client_name']) + r'(?!\w)', message, re.I)}
        if clients:
            return [job for job in jobs if job['client_name'].casefold() in clients], True
        # A BL-looking token outside this scope must never fall through to an all-jobs answer.
        if re.search(r'\b(?:BL|MEDU)[A-Z0-9-]{3,}\b', message, re.I):
            return [], True
        return jobs, False

    def local_answer(self, message, scope, jobs, conversation):
        explanation = re.search(r'^\s*(?:what|which|why|when|how|who)\b', message, re.I)
        mutation = re.search(r'\b(?:delete|remove|update|edit|change|mark|pay|send|approve|submit|upload|create|execute|browse|download)\b|\brun\s+(?:a|the|shell|command)\b|\bopen\s+(?:https?://|file|/)', message, re.I)
        if mutation and not explanation:
            result = self.envelope(scope, [])
            result['text'] = 'I am read-only. I can explain shipment status and pending actions, but cannot change records, send messages, make payments or access other systems.'
            return result, []
        selected, explicit = self.select_message_jobs(message, jobs)
        if not explicit and re.search(r'\b(?:it|that job|that shipment|this job|this shipment|these)\b', message, re.I) and conversation.get('focus'):
            selected = [job for job in jobs if job['id'] in conversation['focus']]
            explicit = True
        result = self.envelope(scope, selected)
        if explicit and not selected:
            result['text'] = 'I cannot find that shipment in the selected visible scope. Use its exact BL or LMC job ID, or change the dashboard selection.'
        elif explicit and len({job['bl'].strip().casefold() for job in selected}) == 1 and len(selected) > 1:
            result['text'] = 'That BL identifies {} separate jobs: {}. Choose an LMC job ID so I keep their records separate.'.format(
                len(selected), ', '.join(job['job_id'] for job in selected[:MAX_CONTEXT_JOBS]))
            result['references'] = [reference(job) for job in selected[:MAX_CONTEXT_JOBS]]
        elif explicit or (explanation and mutation) or re.search(r'\b(?:hi|hello|brief|briefing|next|pending|outstanding|attention|priorities|changed|action|actions|job|jobs|shipment|shipments|status|help|blocker|blockers|delivery|clearing|ecd|duty|paar|obl|eta|tdo|customs|warehouse)\b', message, re.I):
            result['text'] = self.briefing_text(result)
            if re.search(r'\bchanged\b', message, re.I):
                result['text'] = 'I can show current pending actions; this chat does not read audit or change history.\n' + result['text']
            if explicit and len(selected) == 1:
                job = selected[0]
                result['text'] = '{} · {} · {}.\n{}'.format(job['job_id'], job['bl'], job['state'], result['text'])
                if not result['references']:
                    result['references'] = [reference(job)]
        else:
            result['text'] = 'I can brief you on visible shipments and their pending actions. Ask “What needs my attention?”, or include an exact BL or LMC job ID. General conversation is unavailable in local guided mode.'
            result['references'] = []
            result['actions'] = []
        return result, selected

    def chat(self, session, body):
        allowed = {'message', 'conversation_id', 'turn_id', *SCOPE_KEYS}
        if set(body) - allowed:
            raise ApiError(400, 'Unknown Jarvis request fields.')
        message = body.get('message')
        if not isinstance(message, str) or not message.strip() or len(message) > 2000 or any(ord(char) < 32 and char not in '\n\t' for char in message):
            raise ApiError(400, 'Message must contain 1–2000 text characters.')
        message = message.strip()
        identifier = body.get('conversation_id')
        turn_id = body.get('turn_id', uuid.uuid4().hex)
        if (identifier is not None and (not isinstance(identifier, str) or not SAFE_ID.fullmatch(identifier))) or not isinstance(turn_id, str) or not SAFE_ID.fullmatch(turn_id):
            raise ApiError(400, 'Conversation and turn IDs must contain 16–100 safe characters.')
        scope, jobs = self.load(body)
        visible_ids = tuple(sorted(job['id'] for job in jobs))
        owner = session['token_hash']
        fingerprint = hashlib.sha256(json.dumps({'message': message, 'scope': scope_key(scope), 'conversation_id': identifier}, sort_keys=True).encode()).hexdigest()
        with self.lock:
            now = time.monotonic()
            self.prune(now)
            conversation = self.conversations.get(identifier) if identifier else None
            if identifier and (not conversation or conversation['owner'] != owner):
                raise ApiError(404, 'Conversation is unavailable. Start a new chat.')
            if conversation and conversation['scope'] != scope_key(scope):
                raise ApiError(409, 'The shipment selection changed. Start a new chat for this scope.')
            if conversation and conversation['visible_ids'] != visible_ids:
                raise ApiError(409, 'The visible shipments changed. Start a new chat for the current selection.')
            cached = self.turns.get((owner, turn_id))
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise ApiError(409, 'Turn ID already used with different content.')
                if self.conversations[cached['conversation_id']]['visible_ids'] != visible_ids:
                    raise ApiError(409, 'The visible shipments changed. Start a new chat for the current selection.')
                return copy.deepcopy(cached['response'])
            if conversation is None:
                identifier = uuid.uuid4().hex
                conversation = {'owner': owner, 'scope': scope_key(scope), 'history': [], 'focus': [], 'at': now,
                                'visible_ids': visible_ids}
                self.conversations[identifier] = conversation
            result, selected = self.local_answer(message, scope, jobs, conversation)
            connection = result['connection']
            if connection['enabled'] and connection['verified']:
                # Only the small scoped projection crosses the provider boundary; history is from this session.
                context = {'scope': scope, 'briefing': {key: result[key] for key in ('totals', 'actions', 'references', 'limitations')},
                           'shipments': [shipment_dto(job) for job in selected[:MAX_CONTEXT_JOBS]],
                           'truncated': len(selected) > MAX_CONTEXT_JOBS}
                try:
                    reply = self.app.jarvis_provider.respond(message, copy.deepcopy(conversation['history']), context)
                    if not isinstance(reply, str) or not reply.strip() or len(reply) > 12000:
                        raise ValueError('Invalid assistant response')
                    result['text'], result['mode'] = reply.strip(), 'hermes'
                except Exception:
                    result['connection'] = {'enabled': True, 'verified': True, 'reason': 'Hermes could not complete this turn; local guidance is shown.'}
            result.update(conversation_id=identifier, turn_id=turn_id)
            conversation['history'].extend([{'role': 'user', 'content': message}, {'role': 'assistant', 'content': result['text']}])
            conversation['history'] = conversation['history'][-self.max_history_messages:]
            conversation['focus'] = [job['id'] for job in selected[:MAX_CONTEXT_JOBS]]
            conversation['at'] = time.monotonic()
            self.conversations.move_to_end(identifier)
            while len(self.conversations) > self.max_conversations:
                self.conversations.popitem(last=False)
            self.prune(conversation['at'])
            self.turns[(owner, turn_id)] = {'fingerprint': fingerprint, 'conversation_id': identifier, 'response': copy.deepcopy(result)}
            while len(self.turns) > self.max_cached_turns:
                self.turns.popitem(last=False)
            return result


def register(route, ApiError):
    @route('GET', '/api/jarvis/briefing')
    def briefing(req, query, body):
        if set(query) - set(SCOPE_KEYS):
            raise ApiError(400, 'Only department, client and shipment scope filters are supported.')
        return req.app.jarvis.briefing(query)

    @route('POST', '/api/jarvis/chat')
    def chat(req, query, body):
        if query:
            raise ApiError(400, 'Supply chat scope in the JSON body.')
        return req.app.jarvis.chat(req.session, body)
