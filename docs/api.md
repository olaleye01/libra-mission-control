# Libra application API · slices 1–2.1

One local server serves frontend assets and JSON endpoints. API success responses contain `ok: true`; failures contain `ok: false` and an `error` message with the appropriate HTTP status. All API data endpoints require an authenticated owner session. JSON POST bodies must be objects; the request limit is 8 MB and decoded CSV limit is 5 MB. There is no CORS access.

## Owner access

| Method / route | Behavior |
|---|---|
| GET /api/session | Public: configured/authenticated flags; CSRF token only for the current authenticated session |
| POST /api/auth/setup | Public, same-origin: provision the first local owner with `{password}`; refuses once configured |
| POST /api/auth/login | Public, same-origin: `{password}`; sets an HttpOnly session cookie |
| POST /api/auth/logout | Revoke the current session |

Passwords require 10–128 characters. Authentication attempts are rate-limited. Authenticated POST routes require `X-CSRF-Token` matching the current session. A new local owner must provision access personally; no default owner password is shipped. The browser QA fixture uses a separate disposable data directory.

## Clients and sources

| Method / route | Behavior |
|---|---|
| GET /api/clients | Client IDs, names and applied shipment counts |
| POST /api/clients | Create `{name}` with case-insensitive uniqueness |
| GET /api/sources | Available local CSV source IDs (SHA-256), filenames and sizes; no filesystem paths or file contents |

GZI, Dangote and CHI are initial client records, not generated shipment data. GZI and CHI have independently reviewed import profiles. Other clients still return 422 until their report mapping is reviewed.

## Import lifecycle

| Method / route | Behavior |
|---|---|
| POST /api/imports/preview | Stage a CSV and return normalized records/findings; no shipment register changes |
| GET /api/imports | Batches, status, hash, reporting cut-off, client and reconciliation summaries |
| GET /api/imports/{id} | Saved preview including source rows, normalized dates, proposed stages and findings |
| POST /api/imports/{id}/apply | Require `{confirm_test_import:true}`; atomically apply once when no existing-job matches need review; otherwise 409 |

Preview body contains `client_id`, optional `report_date` in YYYY-MM-DD, and either a known `source_id` or `filename` plus `content_base64`. Duplicate source bytes/client reuse the existing batch. A different cut-off on a duplicate source returns 409 rather than changing the saved interpretation silently. Raw import snapshots remain immutable. Report updates attach later source evidence to existing jobs separately.

The summary contains shipment rows, distinct trimmed BLs, repeated-BL groups, physical rows, excluded-row categories, proposed-state counts, warning count and records with warning-level findings. Raw source remains unchanged.

New GZI previews use `mapping:gzi-header-v2`. Columns are matched by normalized known heading aliases, in any order and with optional columns, separately at every repeated header. A recognized, unique BL heading is the identity minimum; S/N and all other headings are optional. Missing BL values do not create anonymous jobs. Known rate-table footers are excluded. Other clients still need reviewed mappings, especially for the report-specific meaning of ATD.

`summary.column_mappings` contains each header's `header_row`, `section`, `mapped` entries (`field`, `label`, one-based `column`, original `header`), `pending` entries with reasons, `ambiguous` duplicates and `unmapped` original headers. `summary.field_labels` supplies display labels; `summary.skipped_rows` reports numbered source rows lacking BL. Mapping never chooses between duplicated headings. In particular, two Gate Out Date columns do not establish warehouse arrival.

Each new record retains actual variable-width `raw` and `source_headers`, plus `field_mapping`, `missing_columns`, `blank_fields`, `unresolved_fields` and their `pending_fields` union. Pending means missing/uninterpretable source data, not confirmation that a document is operationally outstanding. Short rows retain their actual raw length; extra or unfamiliar cells remain in the original. Date/count/reference values absent from the source stay null/empty. Existing batches and applied source snapshots are not rewritten or reparsed; same-file/client retries still reuse their immutable preview.


## Shipment visibility

| Method / route | Behavior |
|---|---|
| GET /api/overview | Counts by displayed state, warning counts, known container count/unknown coverage, mode and connection availability |
| GET /api/shipments | Paginated records, excluding raw cells, source snapshots and detailed operational state |
| GET /api/shipments/{id} | Full record, raw cells, source provenance, normalized dates, findings, immutable source_snapshot, operation, revision, movement events, calculated actions and audited history |
| GET /api/audit | Most recent 30 application events |

Overview/list filters: `client_id`. List additionally supports `search`, `state`, `issues=1`, `page` and `limit` (maximum 100). Shipment IDs are application-generated integers, displayed as LMC-00001 etc. BLs and source serial numbers are not unique identifiers. Internal job IDs are created only when a preview is applied; previews use source-row references.

`proposed_state` and `review_status` distinguish historical interpretation from verified operational state. `pending_count` stays null for unreconciled source proposals. For owner-reconciled jobs it equals the known starting container total minus active warehouse-event quantities. Imported records never infer Completed. Date fields include pre-alert, ETA, berth, PAAR, OBL, final assessment received, duty receipt, exam, Customs release, DO, TDO, gate-out, warehouse arrival, terminal validity and ECD.

## Owner application actions

All POST actions below require owner session + CSRF, a unique safe `command_id` (16–100 characters), and a non-empty `reason`. Use a UUID. Updates also require the integer `revision` returned by the latest shipment read. Stale revisions and reused IDs with different content return 409; rejected requests make no partial writes. Same-ID/body retries return the original response. A new edit after success needs a new ID and fresh revision. Success returns `{ok:true, shipment:{...}}`. All actions remain test-workspace operations.

| Method / route | Behavior |
|---|---|
| POST /api/shipments | Create `{client_id, changes, command_id, reason}`; no import required |
| POST /api/shipments/{id}/update | Apply `{revision, changes, command_id, reason}` as a separate owner record |
| POST /api/shipments/{id}/movements | Append count/date event or correction |
| POST /api/shipments/{id}/followups | Record owner action / awaiting-response metadata; sends nothing |
| GET /api/actions | Calculated internal queue, with optional `client_id` and ISO `as_of` filters |

`changes` accepts `bl`, `description`, `terminal`, `liner`, `handler` (legacy alias), `field_agent`, `import_officer`, `sgd` (C Number/SDG alias), `container_size`, `delivery_location` (optional text, maximum 500 characters), `container_count` (integer 1–100000 or null), `approval_by`, `dates`, `reconciled`, `awaiting_duty_receipt`, `rotation`, `release_coverage`, `invoices`, `closure`, `completed`. Unknown fields are rejected. Empty dates normalize to null; all others must be valid ISO YYYY-MM-DD. All choices start unknown when absent. Client cannot be changed through this update endpoint.

- `dates`: first-slice date keys except gate_out/warehouse, plus `draft_approved` (client approval to proceed) and `client_invoiced`. `draft_received` is retained only for compatibility with earlier entries and is not shown or required by the dashboard. Gate-out/warehouse dates are derived from movement events once reconciled. The dashboard temporarily omits both the client approval date and approver from its form and update payload, preserving earlier values. These fields remain supported by the API; an explicitly supplied approval date requires an approver but no draft receipt date. Once PAAR is recorded, the approval follow-up leads to final-assessment follow-up after approval; no separate draft-receipt task is generated. Legacy `draft` follow-up entries remain stored as history and are not treated as evidence of client approval. Final assessment date plus non-empty `sgd` clears requirements without changing approval history.
- `rotation`: `{status:unknown|not_requested|gotten, number:text}`; `not_requested` represents explicit nil.
- `release_coverage`: `{do:count|null, tdo:count|null, customs_release:count|null}`. Counts are cumulative owner-confirmed coverage for the same job; dates alone do not establish scope. Individual container identities are deferred.
- `invoices`: keys `shipping`, `additional`, `terminal`; each has `{request:unknown|not_requested|requested, received:date|null, payment:unknown|not_paid|paid, payment_date:date|null, rated_through:date|null, coverage, applicability:unknown|required|not_applicable, reason:text}`. Coverage is the matching key or `combined` for shipping/terminal. Payment date requires an explicit paid report. A receipt date does not set paid. These are separate factual fields, not a finalized requested/unpaid invoice status vocabulary. No amount/currency/due date is inferred.
- `closure`: keys `empty_returns`, `shipping_final`, each `{applicability:unknown|required|not_applicable, date:date|null, reason:text}`. Not-applicable decisions require reasons here and on invoices. Client invoice and ECD are date fields. Refunds are not a universal completion gate.

`duplicate_reason` acknowledges a distinct job matching an existing client/BL. Such jobs keep separate IDs. Use IDs for mutations; search is a lookup aid and may match multiple jobs.

`exception_reason` can retain an observed release/movement fact that conflicts with prerequisite evidence. It records the exception in history and leaves a current review finding. It never permits unknown/exceeded quantity totals, invalid dates, stale revisions or incomplete closure. Ordinary forward entries reject unsupported TDO or gate-out. Future movement dates are refused. Customs release is not required before TDO, only before gate-out.

A movement body includes `{kind:gate_out|warehouse, quantity:integer, date, revision, reason, command_id}`. Optional `supersedes` identifies an unsuperseded event on this job of the same kind; quantity zero is only valid for such a cancellation. An identical-looking active event returns 409 unless `confirm_duplicate:true` explicitly confirms a separate load. Corrections append rows, and all dependent totals and prerequisites are recalculated. Both kinds require quantity reconciliation and a known total; gate-out counts do not reduce warehouse-pending quantities. Superseded/cancelled rows remain in the detail history.

A follow-up body has `{key, status:open|in_progress|awaiting_response, team, responsible, blocker, next_action, source, revision, reason, command_id}`. Keys are returned by calculated actions, plus `reported_blocker` for a custom next action. Empty custom next_action clears that custom item, retaining the audit event. Standard requirements disappear only when the underlying facts satisfy them; saved follow-up metadata remains in history. The team defaults to import_officer. Empty person uses the job's Import Officer or Field Agent for that team; other teams stay Unassigned. Reminder recipient remains Owner independently. Legacy saved people without a team are preserved as unassigned-team entries with assignment_review:true.

Action objects include key, next_action, status, responsible, blocker, source, last_action_at and as_of; `/api/actions` adds client_name, bl, job_id, shipment_id and historical. Historical jobs use their report cut-off, or no age calculation if unknown; reconciled jobs use today's Africa/Lagos date. `as_of` overrides calculations for review only and never sends or reschedules anything. ECD dates from split delivery require an agreed anchor. Rating-expiry and twice-weekly closure schedules are not implemented.

Operational storage is separate from `import_rows`: `job_updates` holds versioned current facts, `movements` is append-only, `commands` supplies idempotency and `audit` records actor/reason/before/after/revision and movement payload. `source_snapshot` and import preview records remain byte-for-byte equivalent in meaning/content after edits. Schema upgrades preserve v1 IDs, sources and owner sessions and create a private SQLite backup first.

## Delivery location

`delivery_location` is an optional job-level destination/warehouse address, accepted in `changes` for create/update and returned in the shipment list, detail and `operation`. It accepts at most 500 text characters; empty text clears it. Older stored operations and historical imports expose an empty/unknown destination without rewriting their stored source data. Updates use the existing revision/idempotency controls and record before/after values in audit history. Shipment search includes the delivery location. Recording or changing a location does not establish warehouse arrival, change quantities or advance the lifecycle.

## Pending warehouse entry from Update job

The dashboard temporarily hides the warehouse balance controls and reconciliation checkbox. Ordinary form saves omit these fields, preserving existing quantities and reconciliation status. The API below remains supported.

`POST /api/shipments/{id}/update` also accepts an optional top-level `warehouse_balance` object:

```json
{"pending_count": 2, "date": "2024-06-05", "supersedes": null, "confirm_duplicate": false}
```

This is a convenience input for the movement ledger, not a freely editable persisted balance. After validated `changes` are applied, the backend calculates target delivered = saved starting total minus pending_count, and compares it with active warehouse-event quantities. A positive difference appends a warehouse arrival for exactly that difference. Decreasing delivered quantities requires selecting an unsuperseded warehouse event on the same job with `supersedes`; only that event's quantity is adjusted through an append-only replacement. A reduction spanning several events must use the Movements correction controls. A zero replacement cancels the selected event and can retain its original date if no new date is supplied.

The total must be known, pending_count must be an integer from zero through that total, and quantity reconciliation must be explicitly confirmed with `changes.reconciled:true` for unreconciled jobs. New arrivals and nonzero corrections require actual, non-future dates. An unchanged balance creates no event; changing only its date requires selecting an existing event. Duplicate-looking arrivals need explicit confirmation. Release/gate-out count checks, owner-selected warehouse holds, completion gates, revision checks and idempotency remain enforced. Observed-fact exceptions can retain reported arrivals with missing evidence, but cannot fabricate gate-outs or bypass completion requirements.

`warehouse_balance` is allowed only on an existing job update. Direct `changes.pending_count` remains invalid. Job fields, movement insertion, audit record and command result commit together or all roll back. Audit includes the requested balance and any created/corrected movement; original imports remain unchanged. Leaving the input empty on an unreconciled job does not establish a zero delivery count or a delivery date.

## Ownership and coordination (slice 2.1)

`import_officer` and `field_agent` are independent job text fields. The officer initially defaults to Owner; the source's File Handler seeds Field Agent. `handler` remains a compatibility alias to field_agent. An update supplying both aliases with different values returns 422. An explicit clear clears both. Previously saved nonblank Field Agent takes precedence over a conflicting old handler; `operation.legacy_handler` and an ownership_review finding retain that conflict until an explicit assignment update confirms it. Immutable imports and existing audit events are not rewritten. Old operation JSON is normalized on read without database writes; future saves include ownership_version:1 and the updated role fields. Existing explicit follow-up people without a team remain visible for assignment review.

`GET /api/actions` additionally supports `team`, `status` and `queue`. Teams: import_officer, field_agent, accounts, qac, regulatory, unassigned. Statuses: open, in_progress, awaiting_response, resolved (resolved applies to manual items). Queues: all (default), my_next, awaiting_response, clearing_blockers, delivery, closure. Invalid values return 400. Default excludes resolved. Status selection applies before queue selection; resolved items have no active queue membership, so use queue=all when viewing them.

Responses include teams/statuses/queues label dictionaries, team_counts, queue_counts and reminder_recipient:Owner. Team counts are active counts for the client scope; queue counts are active counts for the client and selected team before status/queue narrowing. Items can belong to multiple queues. Each action includes team, team_label, responsible, import_officer, field_agent, reminder_recipient, kind (calculated or coordination), queues, assignment_review when applicable, source, as_of and last_action_at. Manual timestamps refer to the recorded update, not evidence that an external contact occurred. Overview exposes the same client-scoped queue_counts. Known pending warehouse quantities add a delivery_progress follow-up; gate-out still does not imply delivery.

`POST /api/shipments/{id}/coordination` accepts `{command_id, revision, reason, item_id?, item}` with the normal owner session/CSRF and transactional safeguards. Omit item_id to create a new generated item ID; supply an existing ID on that job to edit. Unknown or cross-job IDs return 404. Up to 500 items per job are supported. Item changes accept:

| Field | Values / meaning |
|---|---|
| title | Required non-empty title |
| category | clearing, delivery, closure, regulatory; grouping only |
| team | One of the team keys above; initially import_officer |
| responsible | Optional person; blank uses role-based job assignment where available |
| authority | Optional owner-supplied authority text; no default or inferred requirements |
| status | open, in_progress, awaiting_response, resolved |
| blocker | Owner-reported blocker, not an automatically assumed cause |
| next_action | Required non-empty action |
| source | Required non-empty supporting record/source description |
| blocks_step | Empty (default), tdo, gate_out, warehouse or completion; explicitly selected hold only |
| resolution_note | Required for resolved status |
| resolution_date | Required ISO date for resolved status; may not be future-dated |

The saved item has id, created_at and updated_at. Manual item status does not populate any document or payment field. Resolution removes the item from active queues without deleting it; reopening preserves previous resolution values and audit evidence. Only explicit holds affect forward-entry gates. Observed-fact exceptions can retain reported TDO/movement facts without resolving a hold, within the existing count constraints. Completion holds cannot be bypassed by exception_reason. A completed job must be unmarked before adding an open completion hold. Merely recording a task about a historical release gap does not require repairing the old gap first. Coordination is stored separately from imports under operation.coordination; full before/after audit and shared shipment revision/idempotency rules apply. None of these labels grants staff access or sends notifications.

## Boundaries

No payment execution, deletion, notification-send, Hermes-shell or gateway-control endpoint is included. No arbitrary file path is accepted. Only the four explicit frontend files and two fixed brand-image paths are served; import originals, backups and application data are not static assets. Unknown routes return 404, known routes with another method return 405, and oversize requests return 413 before their body is read.

The owner can view/edit all clients; staff-specific roles remain deferred. Client filtering is applied on the server but is not presented as tenant authorization. Deployment is loopback-only; proxy hosts/TLS and additional access models require explicit future configuration. No live reminder activation or VPS change is implied.

## Reviewed report updates

`GET /api/imports/{id}/review-updates` returns `{ok:true,review:{token,counts,rows,duplicates_to_archive}}`. Counts are `create`, `update`, `unchanged`, `review`. Rows identify source_row, BL, existing shipment_id, revision, duplicate_id, changed before/after values, kept_fields and review notes. Matching is confined to one client and trims/case-folds BL without removing punctuation. Unique cross-report matches update the same job ID. Repeated/ambiguous matches are never merged. Older reporting cut-offs or an already-linked newer upload block replacement. Unknown cut-offs remain unknown.

`POST /api/imports/{id}/review-updates` requires owner/CSRF and `{confirm_test_import:true,plan_token,command_id,reason}`. It recalculates the plan inside a write transaction; a stale token, ambiguous match or operational conflict returns 409 without partial writes. Command IDs have the same strict pattern and replay behavior as shipment commands. Success returns counts and duplicates_archived. A row already attached to this report is unchanged on retries. Missing jobs are never deleted.

The importer merges only usable supplied values into a separate effective source. Empty, missing and uninterpretable values retain earlier facts. Three-way comparison against prior source values preserves independent owner edits, assignments, invoices, tasks, closure and movement events. Changed source-seeded operational values are updated with a revision increment and before/after audit. Reconciled jobs still undergo quantity/release/closure validation; imports do not manufacture movements, approval dates or verified status.

`report_updates` appends immutable batch/source-row links and an effective source record. `source_snapshot` remains the original record; detail adds effective_source, current_source_snapshot and report_history. These raw/effective source objects are omitted from the shipment list. Original physical CSV row and original_filename remain identifiable. `shipment_aliases` archives a prior duplicate without deleting its row or source; only duplicate rows without independent edits, movements or later report history are eligible. Active lists, client counts and action queues exclude archived duplicates. The canonical job and audit retain the duplicate ID. Migration 4 backs up the existing SQLite database before adding these tables.

## CHI import profile

Selecting CHI uses `mapping:chi-header-v1`, with client-scoped aliases in addition to the standard report headings: BOL/AWB NO → bl; COUNT COUNT → container_count; KG/SIZE → container_size for SEA; PAAR Recd Date → paar; OBL Recd Date → obl; Duty Pay Date → duty_receipt; Custom Exam Date → exam; Custom Rel. Date → customs_release; AGENT → handler (Field Agent). The owner confirmed that Duty Pay Date means duty receipt received, rather than a separately reported payment date. It never sets an invoice paid flag.

MODE is preserved as transport_mode and in report_details. For SEA / SEA FREIGHT rows, ATA is berth and TDO / Exit Note Date is tdo. Other/unknown modes retain arrival/exit-note raw evidence and parsed reported dates in report_details, but leave sea berth/tdo and container quantities unknown with a transport_mode_review finding. No weight-to-container conversion or Customs-authority rule is inferred. Original headings/cells and unmapped client/supplier/regulatory details remain in immutable imports. Existing GZI aliases and saved previews are unchanged. CHI report revisions use the same reviewed update mechanism, scoped to the selected client.

## Client and department management

All routes require the existing owner session; writes also require CSRF. Department labels do not grant access. Migration 5 adds departments and client fields department_id, hidden, notes, revision and import_profile. Existing clients are assigned to FMCG 1, keeping their IDs/names and reviewed CSV profiles; an initial assignment audit event is recorded. Startup seeding no longer recreates renamed clients. SQLite backup precedes migration.

- `GET /api/departments`: `{departments:[{id,name,client_count}]}` including departments with no clients.
- `POST /api/departments`: `{name,reason,command_id}` creates a unique department. Names use the same 2–60-character ordinary-text validation as clients.
- `GET /api/clients`: visible client metadata and active shipment counts, including department_name, hidden (boolean), notes, revision and import_profile. Optional department_id/client_id filters and include_hidden=1 permit directory inspection.
- `POST /api/clients`: `{name,department_id,notes,reason,command_id}` creates a client. Missing department_id retains the legacy API default FMCG 1. Existing `{name}` callers remain accepted; the UI supplies a reason and idempotency key. A new display name never grants another client's reviewed import profile.
- `POST /api/clients/{id}/update`: `{revision,changes:{name,department_id,hidden,notes},reason,command_id}`. IDs cannot change; import_profile is not editable here. Missing fields retain their values. Hidden must be boolean, notes are text up to 2000 characters, and department_id must identify a real department.

Client edits require a current integer revision, nonempty reason and safe command_id (16–100 characters). Writes are atomic, bump the revision and audit before/after values. Matching command/body retries replay the original response; stale revisions and changed-body command reuse return 409. UI creation requests also use command replay. Duplicate client/department names return 409. No delete route is provided.

Normal `/api/clients`, `/api/shipments`, `/api/overview`, `/api/actions` and `/api/imports` exclude hidden clients. These routes support department_id plus optional client_id and include_hidden=0|1 (default 0); invalid filters return 400. An explicit include_hidden=1 is for owner review, not a permission bypass. Owner shipment-detail reads retain access to hidden clients' existing jobs. New manual jobs, previews and both report-application paths reject hidden clients with 409 until restored.

Reassignment changes only the client's department link: job/import/operational/movement rows are not moved, cloned or rewritten. Their department context is resolved from the client. Shipment responses include department_id, department_name and client_hidden. Client changes invalidate open report-update review tokens. Import profiles attach to immutable client IDs; renaming/reassignment does not select a different parser or alter historical CSV evidence.

## Automatic MSC tracking

The serving process starts a persistent application scheduler; constructing `Application` or `make_server` in tests does not start it. `Tracking.start_worker()` / `stop_worker()` control its lifecycle. The worker enrols operational MSC jobs without per-job setup or authorisation, using the BL from the job and discovering the explicit Port of Discharge from MSC. It excludes hidden clients, completed jobs and unreconciled historical imports. Other carriers are unsupported. No Hermes, OS cron or notification delivery is involved.

| Method / route | Behaviour |
|---|---|
| GET /api/shipments/{id}/tracking | Automatic eligibility/status, service health, next_due, last 20 attempts, latest successful observation even after many failures, attention conflicts and source events |
| POST /api/shipments/{id}/tracking/check | Optional `{command_id}` refresh; reason and revisions are supplied internally, no setup/reason form; owner session/CSRF required |
| GET /api/shipments/{id}/tracking/{check}/evidence | Owner-authenticated, job-scoped captured plain text; never served as HTML |
| GET /api/overview | Adds client/department-scoped `tracking` service/monitored/finished/attention counts and attention links |

Tracking responses expose `automatic`, `eligible`, `eligibility_reason`, `status`, `service_running`, `scheduled`, `next_due`, `attention`, `config`, `checks`, `latest` and `shipment_revision`. Source observations include original event labels/dates/locations, semantic event IDs, parser version, source URL/timestamp, container coverage and per-container milestones. Date-only source events keep an unknown timezone. Deltas retain new/removed event IDs and milestone differences; repeated checks do not repeat unchanged event changes. Errors include safe codes/phase diagnostics and bounded page evidence where available.

`tracking_configs` JSON persists enrolment identity/count, due time, failures, attention and automatically-owned value provenance; `tracking_checks` retains attempts/evidence/differences. No additional schema beyond migration 6 is needed. First checks become due promptly, then next due is the following 08:00 or 16:00 Lagos slot after success. Failures back off; explicit denials/challenges/browser unavailability use a longer delay. SQL claims prevent overlapping workers across processes, and all carrier starts share a 30-second interval. Expired checks recover without losing prior successful evidence. Shutdown stops new claims; interrupted in-flight work remains recoverable.

Automatic application validates current BL/config identity, operational eligibility and matching known container totals. Only blank, source-seeded or still-source-owned values may change; independent owner changes, including later clear/change-back operations, remain exceptions. Every applied update increments the job revision and audits before/after values with actor `tracking_worker`. Observation, automatic changes, ownership provenance and next schedule commit together. No movement quantities, warehouse arrival, release readiness or job Completed are inferred.

ETA is a forecast. Berth and discharge remain separate; automatic carrier arrival uses destination discharge without rewriting legacy report semantics. The prior TDO follow-up clock remains anchored to berth. Whole-job dates require all carrier containers and a count matching the job. Empty return additionally requires destination discharge, subsequent Import to consignee and later Nigerian Empty received at CY for every expected container. Accepted automatic return evidence finishes tracking independently of clearing-job completion. Partial events remain visible while collection continues.

There is no arbitrary URL, command or credential accepted from a tracking request. The fixed MSC public-page connector uses an isolated browser profile over pipes, expands closed visible sections, retains all source evidence privately, and refuses mismatched identities, unsupported destinations, invalid/future actual dates, active challenges and denial pages. Unknown/missing source fields never erase operational dates.

Legacy owner-only `/tracking/config`, `/tracking/capture` and `/tracking/{check}/review` POST routes remain compatible with the earlier pilot. Their original revision/idempotency/reason checks apply; they have no dashboard forms and are not required for automatic operation. Actual collector availability is an executed validation result, not inferred from scheduler or unit-test success.
