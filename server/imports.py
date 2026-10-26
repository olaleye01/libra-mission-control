"""Reviewed GZI mapping. No silent schema guessing for additional clients."""

import base64
import csv
import datetime as dt
import hashlib
import io
import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path

from store import encode

STATES = ["Awaiting arrival", "In clearing", "In delivery", "Delivered", "Completed"]
DATE_FIELDS = {"pre_alert": 1, "eta": 6, "berth": 7, "paar": 10, "obl": 11,
               "assessment": 12, "duty_receipt": 14, "exam": 15, "customs_release": 16,
               "do": 17, "tdo": 18, "gate_out": 19, "warehouse": 20,
               "terminal_validity": 24, "ecd": 26}
MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
MISSING = {"", "na", "n/a", "nil", "-", "pending"}


def parse_date(raw):
    """Never choose one date from a multiple-date or revision note."""
    value = raw.strip()
    if not value:
        return None, None
    if value.lower() in MISSING:
        return None, "Reported placeholder; not confirmed as not applicable."
    value = re.sub(r"^(?:received on|received|recvd|recv|recd)\s*[:\-]?\s*", "", value, flags=re.I)
    match = re.fullmatch(r"(\d{1,2})[- /]([A-Za-z]{3,9})[- /](\d{2}|\d{4})", value)
    if match:
        day, month, year = match.groups()
        month = MONTHS.get(month[:3].lower())
        year = int(year) + (2000 if len(year) == 2 else 0)
        try:
            return dt.date(year, month, int(day)).isoformat(), None
        except (ValueError, TypeError):
            return None, "Invalid calendar date."
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return dt.date.fromisoformat(value).isoformat(), None
    except ValueError:
        pass
    return None, "Ambiguous date or note; original retained for review."


def preview_csv(content, report_date=None):
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError("Upload a non-empty CSV of at most 5 MB.")
    try:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True))
    except (UnicodeDecodeError, csv.Error):
        raise ValueError("The file must be a valid UTF-8 CSV.")
    if len(rows) > 10000:
        raise ValueError("This preview supports at most 10,000 physical rows.")
    header_index = next((i for i, row in enumerate(rows[:20])
                         if len(row) >= 34 and row[0].strip().upper() == "S/N"
                         and row[3].strip().upper() == "BOL NO"), None)
    if header_index is None:
        raise ValueError("This file does not match the reviewed 34-column GZI report mapping.")
    headers = rows[header_index]
    expected = {1: "PRE-ALERT DATE", 2: "ITEM DESCRIPTION", 4: "TERMINAL", 5: "LINER",
                6: "ETA", 7: "ATD", 16: "CUSTOMS RELEASE DATE", 17: "SHIPPING RELEASE DATE",
                18: "TDO DATE", 19: "GATE OUT DATE", 26: "ECD"}
    if any(headers[i].strip().upper() != name for i, name in expected.items()):
        raise ValueError("Columns differ from the GZI mapping. A new mapping needs review.")
    records, excluded, section = [], Counter(), "Unlabelled"
    section_header = headers
    for number, raw in enumerate(rows, 1):
        if not any(x.strip() for x in raw):
            excluded["Blank rows"] += 1
            continue
        label = raw[0].strip() if raw else ""
        if label.upper() == "S/N":
            if len(raw) != 34:
                raise ValueError(f"Column header at CSV row {number} does not have 34 columns.")
            section_header = raw
            excluded["Repeated / column headers"] += 1
            continue
        if label and not label.isdigit():
            section = label
            excluded["Section labels"] += 1
            continue
        if not label.isdigit() or len(raw) < 4 or not raw[3].strip():
            excluded["Reference / non-shipment rows"] += 1
            continue
        if len(raw) != 34:
            raise ValueError(f"Shipment at CSV row {number} has {len(raw)} columns; expected 34.")
        issues = []

        def issue(code, message, field=None, severity="warning"):
            issues.append({"code": code, "message": message, "field": field, "severity": severity})

        dates = {}
        for field, col in DATE_FIELDS.items():
            value, error = parse_date(raw[col])
            if field == "warehouse" and section_header[20].strip().upper() == "GATE OUT DATE" and raw[col].strip():
                value, error = None, "Section labels this column as gate-out, not factory arrival."
            dates[field] = value
            if error and raw[col].strip().lower() not in MISSING:
                issue("date_review", error, field, "info" if field == "exam" and raw[col].strip().upper() == "AEO" else "warning")
            if value and report_date and field not in ("eta", "terminal_validity") and value > report_date:
                issue("after_cutoff", "Reported event is after the selected reporting date.", field)
        count = int(raw[8].strip()) if raw[8].strip().isdigit() else None
        size_text = raw[9].strip()
        size_match = re.fullmatch(r"(\d+)\s*[xX×]\s*(20|40|45)", size_text)
        size = size_match[2] if size_match else size_text if size_text in ("20", "40", "45") else None
        if size_match:
            parsed_count = int(size_match[1])
            if count is not None and count != parsed_count:
                issue("count_conflict", "Count column disagrees with the count in container size.", "containers")
            elif count is None:
                count = parsed_count
        if not count or not size:
            issue("container_review", "Container count or size is missing or ambiguous.", "containers")
        if not raw[22].strip():
            issue("handler_missing", "No file handler is recorded.", "handler")
        for earlier, later in (("pre_alert", "warehouse"), ("berth", "gate_out"),
                               ("do", "tdo"), ("tdo", "gate_out"),
                               ("customs_release", "gate_out"), ("gate_out", "warehouse")):
            if dates[earlier] and dates[later] and dates[earlier] > dates[later]:
                issue("chronology", f"{earlier.replace('_', ' ').title()} follows {later.replace('_', ' ')}.", later)
        for event, prerequisites in (("tdo", ("do",)), ("gate_out", ("tdo", "customs_release"))):
            if dates[event]:
                for prerequisite in prerequisites:
                    if not dates[prerequisite]:
                        issue("release_gap", f"{event.replace('_',' ').title()} is reported without a dated {prerequisite.replace('_',' ')}.", event)
        comment = raw[21].strip()
        partial = bool(re.search(r"\b(ongoing|awaiting offloading|offloading ongoing|bal\b|balance|remaining|pending.*container)", comment, re.I))
        if partial:
            issue("partial_delivery", "Comment suggests movement or offloading is incomplete; confirm quantities.", "warehouse")
        if (dates["warehouse"] or dates["ecd"]) and not partial:
            state = "Delivered"
            state_note = "Historical delivery proposal from " + ("dated ECD" if dates["ecd"] else "factory arrival") + "; review before relying on it."
            if not dates["warehouse"]:
                issue("delivery_date_missing", "Dated ECD supports delivery, but the warehouse delivery date is unknown.", "warehouse")
        elif dates["gate_out"] or partial:
            state, state_note = "In delivery", "Reported movement; quantities delivered and remaining are not established."
        elif dates["berth"]:
            state, state_note = "In clearing", "Historical proposal from the source's actual berth date."
        else:
            state, state_note = "Awaiting arrival", "No actual berth date recorded; ETA alone does not confirm arrival."
        if re.search(r"awaiting.*release", comment, re.I) and (dates["customs_release"] or dates["do"]):
            issue("comment_conflict", "The comment says awaiting release but release dates are populated.", "comments")
        for col in range(27, 34):
            val = raw[col].strip()
            if val and not re.fullmatch(r"-?[\d,]+(?:\.\d+)?", val):
                issue("finance_type", "A financial column contains non-numeric text; no financial total is calculated.", f"column_{col+1}")
                break
        records.append({"source_row": number, "section": section, "serial": label,
                        "bl": raw[3].strip(), "description": raw[2].strip(), "terminal": raw[4].strip(),
                        "liner": raw[5].strip(), "handler": raw[22].strip(), "sgd": raw[13].strip(),
                        "container_count": count, "container_size": size, "container_raw": size_text,
                        "pending_count": None, "dates": dates, "comments": comment,
                        "proposed_state": state, "state_note": state_note, "issues": issues,
                        "raw": raw, "evidence": "Historical report · not independently verified"})
    if not records:
        raise ValueError("No shipment rows were found in this report.")
    bls = Counter(r["bl"].upper() for r in records)
    for record in records:
        if bls[record["bl"].upper()] > 1:
            record["issues"].append({"code": "duplicate_bl", "severity": "warning", "field": "bl",
                                     "message": "BL repeats in this source. Keep records separate pending review."})
    summary = {"shipments": len(records), "unique_bls": len(bls), "duplicate_groups": sum(v > 1 for v in bls.values()),
               "physical_rows": len(rows), "excluded": dict(excluded), "states": dict(Counter(r["proposed_state"] for r in records)),
               "rows_with_issues": sum(any(i["severity"] == "warning" for i in r["issues"]) for r in records),
               "warning_count": sum(i["severity"] == "warning" for r in records for i in r["issues"])}
    return records, summary


def stage(app, client_id, filename, content, report_date, ApiError):
    try:
        client_id = int(client_id)
    except (ValueError, TypeError):
        raise ApiError(400, "Select a client.")
    if report_date:
        try:
            dt.date.fromisoformat(report_date)
        except (ValueError, TypeError):
            raise ApiError(400, "Reporting date must be YYYY-MM-DD, or left empty.")
    else:
        report_date = None
    filename = Path(str(filename).replace("\\", "/")).name[:160]
    if not filename.lower().endswith(".csv"):
        raise ApiError(400, "Select a CSV file.")
    with app.store.connect() as con:
        client = con.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not client:
        raise ApiError(404, "Client not found.")
    if client["name"].upper() != "GZI":
        raise ApiError(422, "Only the GZI mapping has been reviewed. Additional client mappings follow later.")
    sha = hashlib.sha256(content).hexdigest()
    with app.store.connect() as con:
        existing = con.execute("SELECT * FROM batches WHERE client_id=? AND sha256=?", (client_id, sha)).fetchone()
    if existing:
        if existing["report_date"] != report_date:
            raise ApiError(409, "This source already has a preview with a different reporting date. Use that saved preview.")
        return existing["id"], True
    try:
        records, summary = preview_csv(content, report_date)
    except ValueError as exc:
        raise ApiError(400, str(exc))
    batch_id = uuid.uuid4().hex
    original_dir = app.store.directory / "originals"
    original_dir.mkdir(mode=0o700, exist_ok=True)
    path = original_dir / (sha + ".csv")
    try:
        with path.open("xb") as handle:
            handle.write(content)
        path.chmod(0o600)
    except FileExistsError:
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ApiError(409, "Stored original failed its integrity check.")
    with app.store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT id,report_date FROM batches WHERE client_id=? AND sha256=?", (client_id, sha)).fetchone()
        if existing:
            if existing["report_date"] != report_date:
                raise ApiError(409, "This source already has a preview with a different reporting date.")
            return existing["id"], True
        con.execute("""INSERT INTO batches(id,client_id,filename,sha256,report_date,created_at,summary,mapping)
            VALUES(?,?,?,?,?,?,?,?)""", (batch_id, client_id, filename, sha, report_date, time.time(), encode(summary), "gzi-v1"))
        con.executemany("INSERT INTO import_rows VALUES(?,?,?,?)",
                        ((batch_id, r["source_row"], encode(r["raw"]), encode(r)) for r in records))
        app.store.audit(con, "import_preview_created", {"batch_id": batch_id, "sha256": sha, "rows": len(records)})
    return batch_id, False


def batch_data(app, batch_id, ApiError):
    with app.store.connect() as con:
        batch = con.execute("SELECT b.*,c.name AS client_name FROM batches b JOIN clients c ON c.id=b.client_id WHERE b.id=?", (batch_id,)).fetchone()
        if not batch:
            raise ApiError(404, "Import not found.")
        result = dict(batch)
        result["summary"] = json.loads(result["summary"])
        result["records"] = [json.loads(r[0]) for r in con.execute("SELECT record FROM import_rows WHERE batch_id=? ORDER BY source_row", (batch_id,))]
    return result


def register(route, ApiError):
    @route("GET", "/api/sources")
    def sources(req, query, body):
        return {"sources": req.app.sources()}

    @route("GET", "/api/imports")
    def listing(req, query, body):
        with req.app.store.connect() as con:
            rows = con.execute("SELECT b.*,c.name AS client_name FROM batches b JOIN clients c ON c.id=b.client_id ORDER BY b.created_at DESC").fetchall()
        return {"imports": [dict(r, summary=json.loads(r["summary"])) for r in rows]}

    @route("GET", "/api/imports/<id>")
    def detail(req, query, body):
        return {"batch": batch_data(req.app, req.path_params["id"], ApiError)}

    @route("POST", "/api/imports/preview")
    def preview(req, query, body):
        if body.get("source_id"):
            source = next((s for s in req.app.sources() if s["id"] == body["source_id"]), None)
            if not source:
                raise ApiError(404, "Local source not found.")
            content = (req.app.source_dir / source["filename"]).read_bytes()
            filename = source["filename"]
        else:
            try:
                encoded = body.get("content_base64", "")
                if not isinstance(encoded, str) or len(encoded) > 7 * 1024 * 1024:
                    raise ValueError()
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise ApiError(400, "Invalid file encoding or file exceeds 5 MB.")
            filename = body.get("filename", "report.csv")
        batch_id, reused = stage(req.app, body.get("client_id"), filename, content, body.get("report_date"), ApiError)
        return {"batch": batch_data(req.app, batch_id, ApiError), "reused": reused}

    @route("POST", "/api/imports/<id>/apply")
    def apply(req, query, body):
        if body.get("confirm_test_import") is not True:
            raise ApiError(400, "Confirm that reviewed records are being applied to the test register.")
        batch_id = req.path_params["id"]
        with req.app.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            batch = con.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                raise ApiError(404, "Import not found.")
            reused = batch["status"] == "applied"
            if not reused:
                con.execute("""INSERT INTO shipments(client_id,batch_id,source_row,created_at)
                    SELECT ?,batch_id,source_row,? FROM import_rows WHERE batch_id=?""",
                            (batch["client_id"], time.time(), batch_id))
                con.execute("UPDATE batches SET status='applied' WHERE id=?", (batch_id,))
                req.app.store.audit(con, "test_import_applied", {"batch_id": batch_id, "rows": json.loads(batch["summary"])["shipments"]})
        return {"batch_id": batch_id, "status": "applied", "reused": reused, "mode": "test"}
