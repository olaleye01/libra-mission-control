# Libra Mission Control

A local test workspace for multi-client shipment visibility. The first two slices include owner access, client records, reviewed GZI imports, a searchable register, manual shipment entry, audited milestone/invoice updates, count-based movements, closure checks and internal follow-ups.

Python's standard library is the only backend dependency. The custom HTML/CSS/JavaScript frontend has no package-install or build step.

## Run locally

From this project directory:

```bash
python3 server/server.py
```

Open [http://127.0.0.1:8800](http://127.0.0.1:8800). On first use, create your owner password in the browser. The initial setup endpoint closes once configured. Passwords are salted and hashed with scrypt; sessions are stored as token hashes, expire after eight hours, and use HttpOnly/SameSite=Strict cookies. State-changing authenticated API requests also require a session CSRF token.

The service binds only to 127.0.0.1. This is local development software, not a deployed Dokploy service. Public/reverse-proxy deployment needs a separate reviewed access/network configuration. Do not bind it publicly or reuse the temporary browser-QA password for owner access.

Optional arguments:

```bash
python3 server/server.py --port 8801 --data-dir /tmp/libra-isolated-test
```

The default data directory is this project's `data/`. A different data directory creates an independent workspace with its own owner setup, sessions, clients and import history. Stop the foreground service with Ctrl+C.

## Try the first import

1. Sign in, then select **Import centre**.
2. Choose the available GZI report, or upload a UTF-8 CSV up to 5 MB. Select GZI as the client. Other client records are supported, but their import mappings are not yet implemented.
3. Leave the reporting cut-off blank if it is unknown. Do not infer it from the filename.
4. Build a preview. The GZI importer maps recognized headings in any order; only a recognized BL heading and BL value are needed to identify a shipment. Open **Mapped columns & pending fields** to see what was mapped and what is still to supply. Missing columns, present-but-blank cells and uninterpretable dates remain distinct. Repeated headings and unknown columns are retained for review rather than guessed. Click any BL to inspect milestones, pending information and actual original headings/cells.
5. Select **Apply to test register** and explicitly acknowledge that this is a historical test import. Preview alone never populates the register.
6. Browse Overview, Shipments and QAC review. Search by BL, client, terminal, cargo, handler or SGD, filter by client/state, and inspect source/history in shipment details.

If supplied locally, `imports/sources/GZI-report-26-10-26.csv` is offered as a source without another upload. This private CSV is ignored by Git and is not part of the public assets. A checkout without private data still supports uploads and generated test fixtures.

Repeated section headers can contain different columns. The GZI rate-table footer is excluded, and missing BL values are reported when a source serial identifies a skipped row. Existing saved previews retain their original interpretation; the flexible heading mapping applies to new previews.

Every accepted upload is preserved byte-for-byte in `data/originals/<sha256>.csv`. Imported snapshots retain physical CSV row, section, raw cells, normalized values and findings. Repeated BLs are kept as separate records. Re-uploading the same bytes for the same client opens the existing batch. Applying it again is idempotent. Existing applied records are never silently overwritten by a later upload.

## Source proposals and owner updates

The five labels are Awaiting arrival, In clearing, In delivery, Delivered and Completed. Imported stages are explicitly **historical proposals**, not verified live status. GZI's ATD column maps to actual berthing in Nigeria; other clients need reviewed mappings. A dated ECD can support a Delivered proposal, but it does not invent a delivery date or establish Completed. Partial-delivery notes are flagged; pending quantities stay unknown unless established by later operational entry.

DO, Customs release, TDO, gate-out and factory arrival remain distinct. The importer flags missing prerequisites and inconsistent dates while preserving reported facts. It does not certify release readiness or verify container coverage. Assessment Date means final assessment received. That date plus C Number (SGD/SDG) clears draft-stage requests without inventing approval dates or an approver. Either alone does not trigger that pair rule. Receipt dates and owner-reported paid statuses do not independently verify payment.

## Work with a shipment

Select **Create shipment** to enter a job for any client. Client and BL are explicit; matching BLs are never merged. Creating a separate job with an existing client/BL requires a duplicate reason. Each job has an internal LMC ID.

Open a job and use its tabs:

1. **Update job**: correct descriptive fields, record documents and actual approval history, confirm release counts, rotation and closure applicability. Every save needs a reason and records before/after values.
2. **Invoices**: keep request, receipt, reported payment, payment date, rated-through coverage and applicability separate. Nil means not requested; blank/unknown never becomes unpaid or not applicable. A received combined shipping/terminal invoice suppresses duplicate collection requests. Requested/unpaid invoices use separate factual fields while final terminology remains open.
3. **Movements**: record gate-out and warehouse counts/dates separately. DO precedes TDO; DO, TDO and Customs release dates/count coverage must support gate-out. Customs release may follow TDO. Warehouse counts cannot exceed accounted gate-out by that date, and neither total can exceed the starting container total. Explicit reported exceptions preserve observed conflicting facts and remain review findings; they cannot bypass quantity totals or completion checks.
4. **Follow-ups**: record a responsible person, reported blocker, next action and source. Sending a request means awaiting response, not fulfilled. This screen sends no messages.
5. **Source & history**: see unchanged import cells alongside audited owner changes. Movement corrections append a replacement event; zero cancels a selected event while retaining its history. Identical count/date/type loads need explicit confirmation to prevent accidental double-counting.

For imported jobs, confirming quantity reconciliation is an explicit owner action. Existing source dates never generate movement quantities. Until reconciled, the original proposed stage remains visible and pending counts stay unknown. Reconciliation switches progress to entered event counts; enter all known historical movements, with exception reasons for missing release evidence. All data remains in the test workspace.

All containers at the warehouse means Delivered. Completed additionally requires ECD, client invoicing, applicable empty returns and applicable shipping-line final invoice. Unknown applicability blocks completion; not applicable requires a reason. Refund settlement is not a universal gate. Fixing a completed job in a way that invalidates closure requires explicitly unmarking Completed.

The **Outstanding actions** page calculates internal follow-ups: five calendar days before ETA, assessment/duty receipt, requested invoices/reported unpaid invoices, more than five days since actual berth without dated TDO, ECD after seven days and closure. Missing source dates/statuses require confirmation. Historical date calculations use a supplied report cut-off; unknown cut-offs do not become today's age. Split warehouse-delivery dates show an unresolved ECD anchor. Rating-expiry actions, closure weekdays and all external reminder scheduling remain deferred.

Saves are transactional and revision checked. Repeating the same command ID/body returns its original result; changing that body or saving a stale revision returns 409. A pre-slice-2 SQLite backup is created under the application's private data/backups before upgrading a first-slice database; imports, internal IDs and owner access are preserved. Backups contain private data and must remain outside source control.

## Next

Hermes chat/tools, Telegram shipment actions, scheduled notifications, Odoo and additional client CSV mappings remain later slices. Manual jobs already support all clients. No Hermes profiles, credentials, gateway or routing are changed. There is no live deployment or outbound notification transport in this build.

## Checks

```bash
python3 -m unittest discover -s tests -v
node --check frontend/app.js
```

Tests use temporary storage and ephemeral loopback ports. They cover importer mapping, duplicate preservation, historical status evidence, partial delivery, release gaps, counts, malformed files, authentication, origin/Host checks, CSRF, file boundaries, repeated imports, confirmation, persistence, client filters and audit history. The operational suite also covers assessment clearance, count/release prerequisites, exceptions, duplicate loads, corrections, completion gates, calendar boundaries, concurrent revisions, migration backups and persistence. Real-source reconciliation is skipped if the private CSV is not available.

See `docs/api.md` for the lightweight API contract. Private planning notes, verification screenshots and client reports remain local and are excluded from the repository.
