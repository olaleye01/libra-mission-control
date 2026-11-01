import json
from collections import Counter

from imports import STATES
from records import records
from operations import date, choice
from coordination import TEAMS, STATUSES, QUEUES, counts
from client_scope import filtered
from workflow import today


def overview_highlights(jobs):
    """Summarise existing evidence; ordering never creates a new workflow deadline."""
    priorities = {'tdo_age': 1, 'duty_receipt': 2, 'delivery_progress': 2, 'ecd': 2,
                  'draft_approval': 3, 'final_assessment': 3, 'assessment_details': 3,
                  'shipping_invoice': 4, 'rotation': 4, 'paar': 4, 'obl': 4,
                  'terminal_invoice': 4, 'closure': 5}
    next_actions, attention = [], []
    review_count, hold_count = 0, 0
    for job in jobs:
        historical = bool(job.get('batch_id')) and not job['operation']['reconciled']
        active = [item for item in job['actions'] if item['status'] != 'resolved']
        context = {'shipment_id': job['id'], 'bl': job['bl'], 'client_name': job['client_name'],
                   'historical': historical}
        for item in active:
            if 'my_next' not in item['queues']:
                continue
            priority = 0 if item.get('blocks_step') or item.get('blocker') else priorities.get(item['key'], 6)
            next_actions.append((priority, job['id'], item['key'], {
                **context, 'key': item['key'], 'next_action': item['next_action'],
                'status': item['status'], 'as_of': item['as_of'], 'source': item.get('source', ''),
                'kind': item['kind'], 'tab': 'coordination' if item['kind'] == 'coordination' else 'followups'}))
        warnings = [issue for issue in job['issues'] if issue['severity'] == 'warning']
        holds = [item for item in active if item.get('blocks_step')]
        blockers = [item for item in active if item.get('blocker')]
        review_count += bool(warnings)
        hold_count += bool(holds)
        # The count is jobs, not issues; repeated BL values still have different internal IDs.
        if not (warnings or holds or blockers):
            continue
        as_of = (job.get('report_date') if not job['operation']['reconciled'] else
                 next((a['as_of'] for a in active if a['as_of']), None) or today())
        if holds:
            item = sorted(holds, key=lambda item: (item['blocks_step'], item['key']))[0]
            title = 'Process hold · ' + {'tdo': 'TDO', 'gate_out': 'Gate-out', 'warehouse': 'Warehouse arrival',
                                       'completion': 'Completion'}[item['blocks_step']]
            detail = item.get('title') or item['next_action']
            tab, kind, priority = 'coordination', 'hold', 0
        elif blockers:
            item = sorted(blockers, key=lambda item: item['key'])[0]
            title, detail = 'Reported blocker', item['blocker']
            tab = 'coordination' if item['kind'] == 'coordination' else 'followups'
            kind, priority = 'blocker', 1
        else:
            # A warning describes a record question, not confirmed missing documents or noncompliance.
            issue = sorted(warnings, key=lambda issue: (issue.get('code', ''), issue.get('field', ''), issue['message']))[0]
            title, detail = 'Record needs review', issue['message']
            tab, kind, priority = 'milestones', 'review', 2
        attention.append((priority, job['id'], {**context, 'title': title, 'detail': detail,
                                              'tab': tab, 'kind': kind, 'as_of': as_of}))

    # Several actions for one BL must not crowd other jobs out of the short briefing.
    selected, seen = [], set()
    for _, identifier, _, item in sorted(next_actions, key=lambda item: item[:3]):
        if identifier not in seen:
            seen.add(identifier)
            selected.append(item)
        if len(selected) == 3:
            break
    return {'briefing': {'action_count': len(next_actions),
                         'shipment_count': len({item[1] for item in next_actions}),
                         'undated_count': sum(item[3]['as_of'] is None for item in next_actions),
                         'items': selected},
            'attention': {'shipment_count': len(attention), 'review_count': review_count, 'hold_count': hold_count,
                          'items': [item[2] for item in sorted(attention, key=lambda item: item[:2])[:4]]}}


def all_records(app, client_id=None, as_of=None):
    with app.store.connect() as con:
        return records(con, client_id, as_of)


def register(route, ApiError):
    def client_filter(query):
        value = query.get("client_id")
        if value and not value.isdigit():
            raise ApiError(400, "Invalid client filter.")
        return value

    @route("GET", "/api/overview")
    def overview(req, query, body):
        records = filtered(all_records(req.app, client_filter(query)), query)
        states = Counter(r["state"] for r in records)
        terminal_counts = Counter(r["terminal"] for r in records)
        return {"total": len(records), "states": {s: states[s] for s in STATES},
                "rows_with_issues": sum(any(i["severity"] == "warning" for i in r["issues"]) for r in records),
                "warning_count": sum(i["severity"] == "warning" for r in records for i in r["issues"]),
                "known_container_total": sum(r["container_count"] or 0 for r in records),
                "unknown_container_count": sum(not r["container_count"] for r in records),
                "terminals": dict(terminal_counts.most_common(5)),
                "action_count": sum(a["status"] != "resolved" for r in records for a in r["actions"]),
                "queue_counts": counts([a for r in records for a in r["actions"]]),
                "tracking": req.app.tracking.summary(records),
                **overview_highlights(records),
                "mode": "test", "hermes": "not_connected", "notifications": "disabled"}

    @route("GET", "/api/shipments")
    def listing(req, query, body):
        records = filtered(all_records(req.app, client_filter(query)), query)
        state = query.get("state", "")
        if state and state not in STATES:
            raise ApiError(400, "Unknown shipment state.")
        search = query.get("search", "").strip().lower()
        if len(search) > 120:
            raise ApiError(400, "Search is limited to 120 characters.")
        if state:
            records = [r for r in records if r["state"] == state]
        if search:
            records = [r for r in records if search in " ".join(str(r[k]) for k in ("job_id", "bl", "description", "terminal", "liner", "field_agent", "import_officer", "delivery_location", "sgd", "client_name")).lower()]
        if query.get("issues") == "1":
            records = [r for r in records if any(i["severity"] == "warning" for i in r["issues"])]
        try:
            page = max(1, int(query.get("page", 1)))
            limit = max(1, min(100, int(query.get("limit", 15))))
        except (TypeError, ValueError):
            raise ApiError(400, "Page and limit must be integers.")
        total = len(records)
        selected = records[(page-1)*limit:page*limit]
        return {"shipments": [{k: v for k, v in r.items() if k not in ("raw", "source_snapshot", "current_source_snapshot", "effective_source", "report_history", "movements", "operation")} for r in selected],
                "total": total, "page": page, "limit": limit}

    @route("GET", "/api/shipments/<id>")
    def detail(req, query, body):
        identifier = req.path_params["id"]
        if not identifier.isdigit():
            raise ApiError(400, "Invalid shipment ID.")
        # Scope the read through the authenticated application store, not a supplied file path.
        record = next((r for r in all_records(req.app) if r["id"] == int(identifier)), None)
        if not record:
            raise ApiError(404, "Shipment not found.")
        with req.app.store.connect() as con:
            history = con.execute("SELECT at,actor,action,detail FROM audit ORDER BY id").fetchall()
        record["history"] = [{"at": r["at"], "actor": r["actor"], "action": r["action"], "detail": json.loads(r["detail"])}
                             for r in history if (record["batch_id"] and json.loads(r["detail"]).get("batch_id") == record["batch_id"])
                             or json.loads(r["detail"]).get("shipment_id") == record["id"]]
        return {"shipment": record}

    @route("GET", "/api/actions")
    def actions(req, query, body):
        as_of = date(query.get("as_of"))
        jobs = filtered(all_records(req.app, client_filter(query), as_of), query)
        team = choice(query.get('team', ''), ('', *TEAMS), 'team filter')
        status = choice(query.get('status', ''), ('', *STATUSES), 'status filter')
        queue = choice(query.get('queue', 'all'), ('all', *QUEUES), 'queue filter')
        items = [{**a, 'shipment_id': r['id'], 'job_id': r['job_id'], 'client_name': r['client_name'],
                  'bl': r['bl'], 'historical': not r['operation']['reconciled']}
                 for r in jobs for a in r['actions']]
        team_counts = {key: sum(a['team'] == key and a['status'] != 'resolved' for a in items) for key in TEAMS}
        if team:
            items = [a for a in items if a['team'] == team]
        queue_counts = counts(items)
        if status:
            items = [a for a in items if a['status'] == status]
        else:
            items = [a for a in items if a['status'] != 'resolved']
        if queue != 'all':
            items = [a for a in items if queue in a['queues']]
        return {'actions': items, 'queue_counts': queue_counts, 'team_counts': team_counts, 'teams': TEAMS,
                'queues': QUEUES, 'statuses': STATUSES, 'notifications': 'disabled', 'reminder_recipient': 'Owner'}

    @route("GET", "/api/audit")
    def audit(req, query, body):
        with req.app.store.connect() as con:
            rows = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 30").fetchall()
        return {"events": [dict(r, detail=json.loads(r["detail"])) for r in rows]}
