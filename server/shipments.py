import json
from collections import Counter

from imports import STATES
from records import records
from operations import date, choice
from coordination import TEAMS, STATUSES, QUEUES, counts


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
        records = all_records(req.app, client_filter(query))
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
                "mode": "test", "hermes": "not_connected", "notifications": "disabled"}

    @route("GET", "/api/shipments")
    def listing(req, query, body):
        records = all_records(req.app, client_filter(query))
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
        return {"shipments": [{k: v for k, v in r.items() if k not in ("raw", "source_snapshot", "movements", "operation")} for r in selected],
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
        jobs = all_records(req.app, client_filter(query), as_of)
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
