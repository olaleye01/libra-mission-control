import json
from collections import Counter

from imports import STATES


def all_records(app, client_id=None):
    with app.store.connect() as con:
        sql = """SELECT s.id,s.client_id,s.batch_id,s.source_row,c.name AS client_name,
            b.filename,b.report_date,r.record FROM shipments s
            JOIN clients c ON c.id=s.client_id JOIN batches b ON b.id=s.batch_id
            JOIN import_rows r ON r.batch_id=s.batch_id AND r.source_row=s.source_row"""
        args = ()
        if client_id:
            sql += " WHERE s.client_id=?"
            args = (client_id,)
        rows = con.execute(sql + " ORDER BY s.created_at DESC,s.source_row DESC", args).fetchall()
        records = []
        for row in rows:
            r = dict(row)
            r.update(json.loads(r.pop("record")))
            r["job_id"] = f"LMC-{r['id']:05d}"
            r["state"] = r["proposed_state"]
            r["review_status"] = "Historical proposal"
            records.append(r)
        return records


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
            records = [r for r in records if search in " ".join(str(r[k]) for k in ("job_id", "bl", "description", "terminal", "liner", "handler", "sgd", "client_name")).lower()]
        if query.get("issues") == "1":
            records = [r for r in records if any(i["severity"] == "warning" for i in r["issues"])]
        try:
            page = max(1, int(query.get("page", 1)))
            limit = max(1, min(100, int(query.get("limit", 15))))
        except (TypeError, ValueError):
            raise ApiError(400, "Page and limit must be integers.")
        total = len(records)
        selected = records[(page-1)*limit:page*limit]
        return {"shipments": [{k: v for k, v in r.items() if k != "raw"} for r in selected],
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
        record["history"] = [{"at": r["at"], "actor": r["actor"], "action": r["action"]}
                             for r in history if json.loads(r["detail"]).get("batch_id") == record["batch_id"]]
        return {"shipment": record}

    @route("GET", "/api/audit")
    def audit(req, query, body):
        with req.app.store.connect() as con:
            rows = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 30").fetchall()
        return {"events": [dict(r, detail=json.loads(r["detail"])) for r in rows]}
