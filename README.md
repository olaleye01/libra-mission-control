# Libra Mission Control

A local test workspace for multi-client shipment visibility. Slices 1–2.1 include owner access, client records, reviewed GZI imports, a searchable register, manual shipment entry, audited milestone/invoice updates, count-based movements, closure checks internal follow-ups and an Import Officer coordination desk.

Python's standard library is the only backend dependency. The custom HTML/CSS/JavaScript frontend has no package-install or build step.

## Run locally

From this project directory:

```bash
python3 server/server.py
```

Open [http://127.0.0.1:8800](http://127.0.0.1:8800). On first use, create your owner password in the browser. The initial setup endpoint closes once configured. Passwords are salted and hashed with scrypt; sessions are stored as token hashes, expire after eight hours, and use HttpOnly/SameSite=Strict cookies. State-changing authenticated API requests also require a session CSRF token.

The service binds only to 127.0.0.1. This is local development software, not a deployed Dokploy service. Public/reverse-proxy deployment needs a separate reviewed access/network configuration. Do not bind it publicly or reuse the temporary browser-QA password for owner access.

Use the button beside the Libra logo to collapse the sidebar into a compact navigation rail or expand it again. The desktop choice is remembered in this browser. On phones, use the menu button to open navigation; close it with the sidebar close button, Escape, or a tap outside.

Optional arguments:

```bash
python3 server/server.py --port 8801 --data-dir /tmp/libra-isolated-test
```

The default data directory is this project's `data/`. A different data directory creates an independent workspace with its own owner setup, sessions, clients and import history. Stop the foreground service with Ctrl+C.

## Try the first import

1. Sign in, then select **Import centre**.
2. Upload a UTF-8 CSV up to 5 MB and select the matching client. GZI and CHI report mappings are supported. Other client records can be used for manual jobs while their report mappings await review.
3. Leave the reporting cut-off blank if it is unknown. Do not infer it from the filename.
4. Build a preview. The GZI importer maps recognized headings in any order; only a recognized BL heading and BL value are needed to identify a shipment. Open **Mapped columns & pending fields** to see what was mapped and what is still to supply. Missing columns, present-but-blank cells and uninterpretable dates remain distinct. Repeated headings and unknown columns are retained for review rather than guessed. Click any BL to inspect milestones, pending information and actual original headings/cells.
5. Select **Apply to test register**, review which rows update existing jobs or create new ones, enter a reason and explicitly acknowledge that this is a historical test import. Preview alone never populates the register.
6. Browse Overview, Shipments and QAC review. Search by BL, client, terminal, cargo, handler or SGD, filter by client/state, and inspect source/history in shipment details.

If supplied locally, `imports/sources/GZI-report-26-10-26.csv` is offered as a source without another upload. This private CSV is ignored by Git and is not part of the public assets. A checkout without private data still supports uploads and generated test fixtures.

Repeated section headers can contain different columns. The GZI rate-table footer is excluded, and missing BL values are reported when a source serial identifies a skipped row. Existing saved previews retain their original interpretation; the flexible heading mapping applies to new previews.

Every accepted upload is preserved byte-for-byte in `data/originals/<sha256>.csv`. Imported snapshots retain physical CSV row, section, raw cells, normalized values and findings. Repeated BLs are kept as separate records. Re-uploading the same bytes for the same client opens the existing batch. Applying it again is idempotent. Changed reports use a reviewed match on client plus BL: a unique match updates the same job ID, and unmatched BLs create new jobs. Repeated or ambiguous BLs require manual review. Missing, blank or uninterpretable source fields do not clear known values; independent owner edits remain in place. Earlier source snapshots and every accepted CSV stay in history.

## Updated reports and existing duplicates

Open a report in **Import centre** and select **Review report updates** (available on applied reports too). The review lists updates, new jobs, already-linked rows, changed fields and owner values retained. Ambiguous matches, older reports and operational validation conflicts block the whole application. A changed review requires reopening it before applying. Jobs missing from the new file are not deleted.

For duplicates created by the earlier importer, the same review can attach the later source to the earlier job and archive the extra register row, provided that extra row has no independent edits, movements or report history. Both source rows remain stored; active counts show the job once. The review never combines two independently worked jobs. Source & history shows the original source, subsequent reports and audited changes.

## Source proposals and owner updates

The five labels are Awaiting arrival, In clearing, In delivery, Delivered and Completed. Imported stages are explicitly **historical proposals**, not verified live status. GZI's ATD column and CHI's ATA column for SEA rows map to actual berthing in Nigeria. CHI's Duty Pay Date means duty receipt received, per owner confirmation; it does not independently verify payment. Other clients need reviewed mappings. A dated ECD can support a Delivered proposal, but it does not invent a delivery date or establish Completed. Partial-delivery notes are flagged; pending quantities stay unknown unless established by later operational entry.

DO, Customs release, TDO, gate-out and factory arrival remain distinct. The importer flags missing prerequisites and inconsistent dates while preserving reported facts. It does not certify release readiness or verify container coverage. Draft assessment is part of obtaining client approval to proceed with final assessment, not a separately required receipt milestone. Client approval dates and approvers are not captured in the current dashboard; any earlier entries remain preserved. No draft receipt date is needed. Assessment Date means final assessment received. That date plus C Number (SGD/SDG) clears draft-stage requests without inventing approval dates or an approver. Either alone does not trigger that pair rule. Receipt dates and owner-reported paid statuses do not independently verify payment.

## Work with a shipment

Select **Create shipment** to enter a job for any client. Client and BL are explicit. Matching report revisions update a job only after a unique client/BL match is reviewed; repeated BLs within a report remain distinct. Creating a separate job with an existing client/BL requires a duplicate reason. Each job has an internal LMC ID. Its optional **Delivery location** field holds the intended client warehouse or delivery address (up to 500 characters). It is available when creating or updating a job and appears in the shipment summary. Entering a destination does not confirm delivery.

The shipment summary temporarily hides Terminal validity. Its date remains available in Update job and source/history; saved values are preserved.

Open a job and use its tabs:

1. **Update job**: correct descriptive fields, record document dates, confirm release counts, rotation and closure applicability. Every save needs a reason and records before/after values. The warehouse delivery balance controls and quantity-reconciliation checkbox are temporarily hidden here. Saving other edits preserves existing reconciliation and movement history. Pending quantities remain calculated from movement history.
2. **Invoices**: keep request, receipt, reported payment, payment date, rated-through coverage and applicability separate. Nil means not requested; blank/unknown never becomes unpaid or not applicable. A received combined shipping/terminal invoice suppresses duplicate collection requests. Requested/unpaid invoices use separate factual fields while final terminology remains open.
3. **Movements**: record gate-out and warehouse counts/dates separately. DO precedes TDO; DO, TDO and Customs release dates/count coverage must support gate-out. Customs release may follow TDO. Warehouse counts cannot exceed accounted gate-out by that date, and neither total can exceed the starting container total. Explicit reported exceptions preserve observed conflicting facts and remain review findings; they cannot bypass quantity totals or completion checks.
4. **Follow-ups**: record a responsible person, reported blocker, next action and source. Sending a request means awaiting response, not fulfilled. This screen sends no messages.
5. **Source & history**: see unchanged import cells alongside audited owner changes. Movement corrections append a replacement event; zero cancels a selected event while retaining its history. Identical count/date/type loads need explicit confirmation to prevent accidental double-counting.

For imported jobs, confirming quantity reconciliation is an explicit owner action. Existing source dates never generate movement quantities. Until reconciled, the original proposed stage remains visible and pending counts stay unknown. Reconciliation switches progress to entered event counts; enter all known historical movements, with exception reasons for missing release evidence. All data remains in the test workspace.

All containers at the warehouse means Delivered. Completed additionally requires ECD, client invoicing, applicable empty returns and applicable shipping-line final invoice. Unknown applicability blocks completion; not applicable requires a reason. Refund settlement is not a universal gate. Fixing a completed job in a way that invalidates closure requires explicitly unmarking Completed.

The **Outstanding actions** page calculates internal follow-ups: five calendar days before ETA, assessment/duty receipt, requested invoices/reported unpaid invoices, more than five days since actual berth without dated TDO, ECD after seven days and closure. Missing source dates/statuses require confirmation. Historical date calculations use a supplied report cut-off; unknown cut-offs do not become today's age. Split warehouse-delivery dates show an unresolved ECD anchor. Rating-expiry actions, closure weekdays and all external reminder scheduling remain deferred.

Saves are transactional and revision checked. Repeating the same command ID/body returns its original result; changing that body or saving a stale revision returns 409. A pre-slice-2 SQLite backup is created under the application's private data/backups before upgrading a first-slice database; imports, internal IDs and owner access are preserved. Backups contain private data and must remain outside source control.

## Import Officer desk and team coordination

The report's **File Handler is the Field Agent**. The **Import Officer** owns the whole clearing job and defaults to Owner in this owner-only pilot. Create/edit forms show these separately. The register lists the Field Agent; the assigned Import Officer(s) appear once in the persistent job header across its detail tabs. `handler` remains a compatibility alias for `field_agent`; it is no longer an independent responsibility or the default follow-up owner. Original CSV headings/cells remain unchanged.

Use the **Import Officer desk** to filter by client, responsible team and status. Its five overlapping queues show My next actions (open/in-progress actions assigned to the Import Officer), Awaiting responses, Clearing blockers, Delivery progress and Closure. The overview links to these queues. Queue counts are item counts; one item can appear in more than one queue. Team choices are Import Officer, Field Agent, Accounts, QAC, Regulatory and Unassigned. These are coordination labels, not staff accounts or new access permissions.

Calculated follow-ups default to the job's Import Officer. Assign their next action in **Follow-ups**, with a responsible team/person, blocker, source and recorded action. A blank person uses the job's officer or field agent for those teams; other teams remain unassigned until a person is named. The reminder recipient is separately fixed to Owner, and sending remains disabled. Awaiting response does not establish receipt/payment or resolve the underlying requirement. Imported history and older explicit assignments are preserved; old assignments without a team are marked for review rather than silently reassigned.

Use **Team coordination** on a shipment to create multiple manual tasks or regulatory issues. Supply a title, work area, responsible team, next action and source; authority/person/blocker are optional. Statuses are Open, In progress, Awaiting response and Resolved. Resolved needs a note and date. Reopening retains the earlier resolution and audit history. Resolved items remain on the job and can be viewed with the desk's Resolved filter.

No authority list or regulatory requirements are inferred. The detailed Regulatory process is deferred until supplied. You may explicitly record a hold on TDO, gate-out, warehouse arrival or completion. Only that named step is held; the backend blocks a new entry at that step until resolved, while an explicit observed-fact exception can retain a reported movement/release and leaves the hold open. Completion holds cannot be bypassed, and a completed job must be reopened before adding one. Recording coordination about an old source gap does not require inventing missing release facts or changing its original snapshot.

All coordination changes share the shipment revision check, idempotency key and before/after audit history. No service connects to or contacts a team member, authority, client or provider.

## Next

Hermes chat/tools, Telegram shipment actions, scheduled notifications, Odoo and additional client CSV mappings remain later slices. Manual jobs already support all clients. No Hermes profiles, credentials, gateway or routing are changed. There is no live deployment or outbound notification transport in this build.

## Checks

```bash
python3 -m unittest discover -s tests -v
node --check frontend/app.js
```

Tests use temporary storage and ephemeral loopback ports. They cover importer mapping, duplicate preservation, historical status evidence, partial delivery, release gaps, counts, malformed files, authentication, origin/Host checks, CSRF, file boundaries, repeated imports, confirmation, persistence, client filters and audit history. The operational suite also covers assessment clearance, count/release prerequisites, exceptions, duplicate loads, corrections, completion gates, calendar boundaries, concurrent revisions, migration backups and persistence. Real-source reconciliation is skipped if the private CSV is not available.

See `docs/api.md` for the lightweight API contract. Private planning notes, verification screenshots and client reports remain local and are excluded from the repository.

## CHI report mapping

CHI has its own `chi-header-v1` profile: BOL/AWB NO identifies the job, COUNT COUNT means container count, and KG/SIZE supplies container size for SEA rows. PAAR Recd Date, OBL Recd Date, Custom Exam Date, Custom Rel. Date and AGENT map to their corresponding fields. Duty Pay Date is the owner-confirmed duty-receipt date. ATA means berthing and TDO / Exit Note Date means TDO for SEA rows. Non-sea/unknown modes keep arrival, exit-note and weight/count cells for review without converting them into sea berthing, TDO or container quantities. Regulatory, supplier, client-reference and clearing-type columns remain in original source data; no regulatory obligations are inferred. Optional columns, source preservation and reviewed updates use the same safeguards as GZI.

## Clients and departments

All existing pilot clients initially belong to **FMCG 1**. Use the Department selector in the sidebar to switch between a department and All departments. The selector scopes visible clients, shipment totals, QAC queues, actions and report history.

Select **Manage clients** beside YOUR CLIENTS to open **Clients & departments**. Use **Edit client** to change its name, notes or assigned department, or hide it. Hidden clients leave normal navigation, filters, shipment views and report lists. The directory includes hidden clients: choose **Edit / restore** and clear the hide checkbox to restore them. Existing jobs and source history are retained. New jobs and new report applications require the client to be visible. Owner access to existing job details remains available; hiding and departments are organisation settings, not staff permissions.

Use **Add department** to create a destination for reassignment. New-client forms use the selected department, defaulting to FMCG 1. Renames preserve the client ID and its reviewed CSV profile, so renaming GZI or CHI does not disable imports or create another default client on restart. Names, notes, visibility and reassignment changes are revision checked, transactionally audited and accept idempotent commands.

Migration 5 backs up the application SQLite database before adding department/client metadata and assigning the existing clients to FMCG 1. It preserves job IDs, source rows, operational edits, movements, credentials and sessions.

## Automatic MSC tracking

Carrier tracking is part of the system. The running server automatically discovers operational MSC jobs from the shipping-line field and BL, obtains the Nigerian discharge port from MSC, and monitors them until all expected empty containers have been returned. There are no tracking setup, authorisation, reason, paste or routine approval forms. Historical, unreconciled test imports are excluded from live queries; manually created or explicitly reconciled operational jobs are eligible. Hidden clients and completed jobs are excluded. Other carriers remain unsupported until a connector is added.

The first check runs shortly after an eligible job appears. Successful checks persist the next 08:00 or 16:00 Africa/Lagos run; transient failures back off rather than hammering the website. The scheduler starts with `python3 server/server.py`, uses durable SQLite state and stops with the server. It needs no Hermes connection, browser tab left open, OS cron or extra HTTP listener. Test Application instances do not start networking. Tracking is not a notification transport: Telegram and outbound reminders remain off.

Routine, unambiguous carrier changes update empty or source-owned operational dates automatically, with before/after audit and check history. Independent owner corrections and clears remain authoritative; conflicting reports are kept as evidence and shown as exceptions. Transshipment discharge is excluded, actual berthing stays separate, and destination discharge is the carrier arrival basis. Unknown dates never clear known facts. Count mismatches and validation conflicts remain exceptions rather than fabricated quantities or release evidence. Historical source snapshots are not rewritten and the existing berth-based TDO-age clock stays unchanged.

Whole-job discharge and empty return require every expected container, using the last applicable date. Empty return needs the ordered destination-discharge, carrier-collection and Nigerian empty-receipt chain. Finishing carrier monitoring does not establish client warehouse delivery, ECD, invoices or administrative job completion.

The overview surfaces tracking exceptions across the selected clients/department. Each job’s Summary shows automatic status, last successful check, next check and return progress. Carrier tracking history retains event differences, failures and source evidence. A secondary Retry now control is available for attention cases; normal operation requires no clicks.

The collector uses installed Chrome/Chromium with an isolated disposable profile, no browser Python packages and no debugging listener. On macOS it detects Google Chrome; server operators may configure an existing executable using `LIBRA_CHROME_PATH`. Browser installation/runtime setup is deployment work. It uses MSC’s public tracking page, expands visible container histories and validates BL, destination and complete coverage. It does not bypass active verification or access denials. A provider denial is surfaced and retried conservatively; it is never presented as successful tracking or converted into a user data-entry task. Live unattended availability is reported separately in docs/msc_tracking_validation.md.

Migration 6 keeps tracking settings and observations separate from imports and operational facts, with a private backup before upgrading existing storage. Captured source evidence, credentials, private reports and screenshots remain outside Git and public assets. Older owner-only capture/config/review endpoints are retained for compatibility but are not part of the dashboard workflow.

## Libra Circle visual identity

The dashboard uses the official Libra Circle logo and navy/gold/blue palette, with the existing Georgia headings and system sans-serif interface typography retained. The redesigned shell, overview workbench, registers, import views, QAC, coordination desk, forms, shipment drawers and responsive navigation share one stylesheet. The official images are bundled locally under `frontend/assets/`; viewing the app does not request company-site assets or external fonts.

Brand assets are served through two fixed public image routes. Application data, source reports and credentials remain private. See `docs/dashboard_redesign_validation.md` for visual and functional checks.
