"""Client-specific report headings; missing source values remain unknown."""

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
from client_scope import active_client, scope

STATES = ["Awaiting arrival", "In clearing", "In delivery", "Delivered", "Completed"]
DATE_FIELDS = {"pre_alert": 1, "eta": 6, "berth": 7, "paar": 10, "obl": 11,
               "assessment": 12, "duty_receipt": 14, "exam": 15, "customs_release": 16,
               "do": 17, "tdo": 18, "gate_out": 19, "warehouse": 20,
               "terminal_validity": 24, "ecd": 26}
MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
MISSING = {"", "na", "n/a", "nil", "-", "pending"}

# These aliases describe known meanings, not fixed spreadsheet positions.
COLUMNS = [
    ('serial', 'Source serial', ('S/N', 'SN', 'Serial No')),
    ('pre_alert', 'Pre-alert date', ('PRE-ALERT DATE', 'PRE ALERT')),
    ('description', 'Cargo description', ('ITEM DESCRIPTION', 'DESCRIPTION OF GOODS', 'CARGO DESCRIPTION', 'DESCRIPTION')),
    ('bl', 'Bill of Lading', ('BOL NO', 'BOL NUMBER', 'BL', 'BL NO', 'BL NUMBER', 'B/L', 'BILL OF LADING', 'BILL OF LADING NO')),
    ('terminal', 'Terminal', ('TERMINAL', 'PORT / TERMINAL')),
    ('liner', 'Shipping line', ('LINER', 'SHIPPING LINE')),
    ('eta', 'ETA', ('ETA', 'EXPECTED ARRIVAL DATE')),
    ('berth', 'Actual berth · ATA/ATD', ('ATA', 'ATD', 'ACTUAL BERTH', 'ACTUAL BERTH DATE')),
    ('container_count', 'Container count', ('CONT COUNT', 'CONTAINER COUNT', 'NO OF CONTAINERS', 'CONTAINERS')),
    ('container_size', 'Container size', ('CONT SIZE', 'CONTAINER SIZE')),
    ('paar', 'PAAR received', ('PAAR DATE', 'PAAR RECEIVED DATE', 'PAAR')),
    ('obl', 'OBL received', ('OBL RECEIVED DATE', 'OBL RECEIVED', 'OBL DATE', 'OBL')),
    ('assessment', 'Final assessment received', ('ASSESS DATE', 'ASS DATE', 'ASSESSMENT DATE', 'FINAL ASSESSMENT RECEIVED')),
    ('sgd', 'C Number / SGD / SDG', ('SGD NO', 'SDG NO', 'C NUMBER', 'C NO', 'SGD', 'SDG')),
    ('duty_receipt', 'Duty receipt received', ('DUTY RECEIVED DATE', 'DUTY RECEIPT DATE', 'DUTY RECEIPT RECEIVED DATE')),
    ('exam', 'Customs examination', ('CUSTOMS EXAM DATE', 'CUSTOMS EXAMINATION DATE')),
    ('customs_release', 'Customs release', ('CUSTOMS RELEASE DATE', 'CUSTOMS RELEASE')),
    ('do', 'Shipping release · DO', ('SHIPPING RELEASE DATE', 'SHIPPING RELEASE', 'DO', 'DO DATE', 'DELIVERY ORDER', 'DELIVERY ORDER DATE')),
    ('tdo', 'Terminal Delivery Order', ('TDO DATE', 'TDO', 'TERMINAL DELIVERY ORDER', 'TERMINAL DELIVERY ORDER DATE')),
    ('gate_out', 'Gate-out', ('GATE OUT DATE', 'GATE OUT')),
    ('warehouse', 'Factory / warehouse arrival', ('ARRIVAL AT FACTORY', 'ARRIVAL AT CLIENTS FACTORY', 'ARRIVAL AT CLIENT FACTORY', 'WAREHOUSE ARRIVAL', 'WAREHOUSE ARRIVAL DATE', 'DELIVERY DATE')),
    ('comments', 'Comments', ('COMMENTS', 'COMMENT')),
    ('handler', 'Field Agent (source File Handler)', ('FILE HANDLER', 'HANDLER', 'FIELD AGENT')),
    ('remark', 'Remark', ('REMARK', 'REMARKS')),
    ('terminal_validity', 'Terminal validity', ('TERMINAL VALIDTY', 'TERMINAL VALIDITY')),
    ('pca_closure', 'PCA Final Closure', ('PCA FINAL CLOSURE',)),
    ('ecd', 'ECD received', ('ECD', 'ECD DATE', 'ECD RECEIVED DATE')),
    ('clearing_income', 'Clearing income', ('CLEARING INCOME',)),
    ('haulage_income', 'Haulage income', ('HAULAGE INCOME',)),
    ('projected_income', 'Total projected income', ('TOTAL PROJECTED INCOME',)),
    ('clearing_cost', 'Clearing cost', ('CLEARING COST',)),
    ('haulage_cost', 'Haulage cost', ('HAULAGE COST',)),
    ('projected_expenses', 'Total projected expenses', ('TOTAL PROJECTED EXPENSES',)),
    ('projected_profit', 'Projected profit', ('PROJECTED PROFIT',)),
]
LABELS = {key: label for key, label, _ in COLUMNS}


def heading(value):
    return re.sub(r'[^A-Z0-9]', '', value.upper())


ALIASES = {heading(alias): key for key, _, aliases in COLUMNS for alias in aliases}
CHI_ALIASES = dict(ALIASES)
# Owner-confirmed CHI meanings. These aliases must not change the GZI interpretation.
for field, aliases in {
    'bl': ('BOL/AWB NO',), 'paar': ('PAAR Recd Date',), 'obl': ('OBL Recd Date',),
    'container_count': ('COUNT COUNT',), 'container_size': ('KG/SIZE',),
    'duty_receipt': ('Duty Pay Date',), 'exam': ('Custom Exam Date',),
    'customs_release': ('Custom Rel. Date',), 'tdo': ('TDO / Exit Note Date',),
    'handler': ('AGENT',), 'mode': ('MODE',),
}.items():
    CHI_ALIASES.update({heading(alias): field for alias in aliases})
PROFILE_IDS = {'GZI': 'gzi-header-v2', 'CHI': 'chi-header-v1'}


def map_columns(headers, number, section, allow_sparse=True, profile='GZI'):
    aliases = CHI_ALIASES if profile == 'CHI' else ALIASES
    labels = {**LABELS, 'mode': 'Transport mode'}
    positions = {}
    for index, value in enumerate(headers):
        key = aliases.get(heading(value))
        if key:
            positions.setdefault(key, []).append(index)
    if 'bl' not in positions:
        return None
    if not allow_sparse and len(positions) == 1 and sum(bool(v.strip()) for v in headers) > 1:
        return None
    if len(positions['bl']) != 1:
        raise ValueError('Bill of Lading heading repeats at row '+str(number)+'. Give the job identifier column a unique heading.')
    # Duplicate headings carry no reliable choice of source column. Retain both for review.
    mapped = {k: v[0] for k, v in positions.items() if len(v) == 1}
    ambiguous = [{'field': k, 'label': labels[k], 'columns': [i+1 for i in v]} for k, v in positions.items() if len(v) > 1]
    return {'header_row': number, 'section': section, 'positions': mapped,
            'mapped': [{'field': k, 'label': labels[k], 'column': i+1, 'header': headers[i]} for k, i in mapped.items()],
            'pending': [{'field': k, 'label': label, 'reason': 'ambiguous heading' if k in positions else 'column not supplied'}
                        for k, label, _ in COLUMNS if k not in mapped and k != 'serial'],
            'ambiguous': ambiguous,
            'unmapped': [{'column': i+1, 'header': value or 'Unnamed column'} for i, value in enumerate(headers)
                         if heading(value) not in aliases]}


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


def preview_csv(content, report_date=None, profile='GZI'):
    if profile not in PROFILE_IDS:
        raise ValueError('This client needs a reviewed report mapping.')
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError("Upload a non-empty CSV of at most 5 MB.")
    try:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True))
    except (UnicodeDecodeError, csv.Error):
        raise ValueError("The file must be a valid UTF-8 CSV.")
    if len(rows) > 10000:
        raise ValueError("This preview supports at most 10,000 physical rows.")
    records, excluded, section = [], Counter(), "Unlabelled"
    current = None
    reference_section = False
    section_header = []
    mappings, skipped_rows = [], []
    for number, raw in enumerate(rows, 1):
        if not any(x.strip() for x in raw):
            excluded["Blank rows"] += 1
            continue
        serial_index = current['positions'].get('serial') if current else None
        numbered_data = serial_index is not None and serial_index < len(raw) and raw[serial_index].strip().isdigit()
        candidate = None if numbered_data else map_columns(raw, number, section, allow_sparse=current is None, profile=profile)
        if candidate:
            current, section_header = candidate, raw
            reference_section = False
            mappings.append(candidate)
            excluded["Repeated / column headers"] += 1
            continue
        if current is None:
            section = next((x.strip() for x in raw if x.strip()), section)
            excluded["Section labels"] += 1
            continue
        positions = current['positions']
        def supplied(key):
            index = positions.get(key)
            return raw[index] if index is not None and index < len(raw) else ''
        bl = supplied('bl').strip()
        serial = supplied('serial').strip()
        occupied = [i for i, value in enumerate(raw) if value.strip()]
        # The GZI footer starts a separate rate table headed 20ft / 40ft.
        # Its terminal names occupy the old BL column but are not shipments.
        if not bl and len(occupied) >= 2 and all(re.fullmatch(r'(20|40|45)FT', heading(raw[i])) for i in occupied):
            reference_section = True
        if reference_section:
            excluded['Reference / non-shipment rows'] += 1
            continue
        if not bl:
            if len(occupied) == 1 and not serial.isdigit():
                section = raw[occupied[0]].strip()
                excluded["Section labels"] += 1
            else:
                excluded["Reference / non-shipment rows"] += 1
                if serial.isdigit():
                    skipped_rows.append({'source_row': number, 'reason': 'BL value missing; row retained in original file, not applied as a shipment.'})
            continue
        # Existing business rules consume named values in their established internal order.
        # The actual raw row and its actual headings are always stored separately.
        cells = [supplied(key) for key, _, _ in COLUMNS]
        issues = []

        def issue(code, message, field=None, severity="warning"):
            issues.append({"code": code, "message": message, "field": field, "severity": severity})

        mode = supplied('mode').strip().upper() if profile == 'CHI' else ''
        sea = mode in ('SEA', 'SEA FREIGHT', 'SEAFREIGHT')
        missing_columns = [item['field'] for item in current['pending']]
        blank_fields = [key for key in positions if key != 'serial' and not supplied(key).strip()]
        if missing_columns:
            issue('columns_pending', 'Some fields were not supplied as usable columns. They remain pending / unknown, not confirmed outstanding documents.', severity='info')
        for ambiguous in current['ambiguous']:
            issue('column_ambiguous', ambiguous['label']+' has repeated headings; values retained without choosing a column.', ambiguous['field'])
        dates = {}
        for field, col in DATE_FIELDS.items():
            value, error = parse_date(cells[col])
            if profile == 'CHI' and not sea and field in ('berth', 'tdo'):
                # ATA and the shared TDO/Exit Note heading are mode-dependent, not warehouse evidence.
                value = None
            dates[field] = value
            if error and cells[col].strip().lower() not in MISSING:
                issue("date_review", error, field, "info" if field == "exam" and cells[col].strip().upper() == "AEO" else "warning")
            if value and report_date and field not in ("eta", "terminal_validity") and value > report_date:
                issue("after_cutoff", "Reported event is after the selected reporting date.", field)
        unresolved_fields = [key for key in DATE_FIELDS if supplied(key).strip() and not dates[key]]
        count = int(cells[8].strip()) if cells[8].strip().isdigit() else None
        size_text = cells[9].strip()
        size_match = re.fullmatch(r"(\d+)\s*[xX×]\s*(20|40|45)", size_text)
        size = size_match[2] if size_match else size_text if size_text in ("20", "40", "45") else None
        if size_match:
            parsed_count = int(size_match[1])
            if count is not None and count != parsed_count:
                issue("count_conflict", "Count column disagrees with the count in container size.", "containers")
            elif count is None:
                count = parsed_count
        if profile == 'CHI' and not sea:
            count, size = None, None
            issue('transport_mode_review', 'Non-sea or unknown mode: ATA, TDO/exit note and weight/count cells are retained for review, not converted to sea milestones or container quantities.', 'mode')
        if not count or not size:
            issue("container_review", "Container count or size is missing or ambiguous.", "containers")
        if not cells[22].strip():
            issue("handler_missing", "No field agent is recorded in the source File Handler column.", "handler")
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
        comment = cells[21].strip()
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
            val = cells[col].strip()
            if val and not re.fullmatch(r"-?[\d,]+(?:\.\d+)?", val):
                issue("finance_type", "A financial column contains non-numeric text; no financial total is calculated.", f"column_{col+1}")
                break
        records.append({"source_row": number, "section": section, "serial": serial,
                        "bl": cells[3].strip(), "description": cells[2].strip(), "terminal": cells[4].strip(),
                        "liner": cells[5].strip(), "handler": cells[22].strip(), "sgd": cells[13].strip(),
                        "container_count": count, "container_size": size, "container_raw": size_text,
                        "pending_count": None, "dates": dates, "comments": comment,
                        "proposed_state": state, "state_note": state_note, "issues": issues,
                        "raw": raw, "source_headers": section_header,
                        "field_mapping": current['mapped'], "missing_columns": missing_columns,
                        "blank_fields": blank_fields, "unresolved_fields": unresolved_fields,
                        "pending_fields": list(dict.fromkeys(missing_columns + blank_fields + unresolved_fields)),
                        "evidence": "Historical report · not independently verified"})
        if profile == 'CHI':
            records[-1]['transport_mode'] = mode
            records[-1]['report_details'] = {
                'mode': mode, 'kg_size_raw': supplied('container_size'),
                'count_raw': supplied('container_count'),
                'arrival_date_reported': parse_date(supplied('berth'))[0],
                'exit_note_date_reported': parse_date(supplied('tdo'))[0] if mode == 'AIR' else None,
            }
    if not mappings:
        raise ValueError("No recognized Bill of Lading heading found. Include BL, BOL NO or Bill of Lading; other columns are optional.")
    if not records:
        raise ValueError("No shipment rows with a Bill of Lading value were found in this report.")
    bls = Counter(r["bl"].upper() for r in records)
    for record in records:
        if bls[record["bl"].upper()] > 1:
            record["issues"].append({"code": "duplicate_bl", "severity": "warning", "field": "bl",
                                     "message": "BL repeats in this source. Keep records separate pending review."})
    summary = {"shipments": len(records), "unique_bls": len(bls), "duplicate_groups": sum(v > 1 for v in bls.values()),
               "physical_rows": len(rows), "excluded": dict(excluded),
               "column_mappings": [{k: v for k, v in mapping.items() if k != 'positions'} for mapping in mappings],
               "field_labels": LABELS, "skipped_rows": skipped_rows, "states": dict(Counter(r["proposed_state"] for r in records)),
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
        client = active_client(con, client_id)
    profile = next((name for name, identifier in PROFILE_IDS.items() if identifier == client['import_profile']), None)
    if profile is None:
        raise ApiError(422, "GZI and CHI report mappings are available. This client still needs a reviewed mapping.")
    sha = hashlib.sha256(content).hexdigest()
    with app.store.connect() as con:
        existing = con.execute("SELECT * FROM batches WHERE client_id=? AND sha256=?", (client_id, sha)).fetchone()
    if existing:
        if existing["report_date"] != report_date:
            raise ApiError(409, "This source already has a preview with a different reporting date. Use that saved preview.")
        return existing["id"], True
    try:
        records, summary = preview_csv(content, report_date, profile)
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
            VALUES(?,?,?,?,?,?,?,?)""", (batch_id, client_id, filename, sha, report_date, time.time(), encode(summary), PROFILE_IDS[profile]))
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
        selection = scope(query)
        with req.app.store.connect() as con:
            rows = con.execute("SELECT b.*,c.name AS client_name,c.department_id,c.hidden AS client_hidden FROM batches b JOIN clients c ON c.id=b.client_id ORDER BY b.created_at DESC").fetchall()
            rows = [r for r in rows if (selection['include_hidden'] or not r['client_hidden'])
                    and (selection['department_id'] is None or r['department_id'] == selection['department_id'])
                    and (selection['client_id'] is None or r['client_id'] == selection['client_id'])]
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
            active_client(con, batch['client_id'])
            reused = batch["status"] == "applied"
            if not reused:
                from report_updates import plan
                review = plan(con, batch_id)
                if review['counts']['update'] or review['counts']['review']:
                    raise ApiError(409, 'This report contains existing BLs. Review report updates before applying; no duplicates were created.')
                con.execute("""INSERT INTO shipments(client_id,batch_id,source_row,created_at)
                    SELECT ?,batch_id,source_row,? FROM import_rows WHERE batch_id=?""",
                            (batch["client_id"], time.time(), batch_id))
                con.execute("UPDATE batches SET status='applied' WHERE id=?", (batch_id,))
                req.app.store.audit(con, "test_import_applied", {"batch_id": batch_id, "rows": json.loads(batch["summary"])["shipments"]})
        return {"batch_id": batch_id, "status": "applied", "reused": reused, "mode": "test"}
