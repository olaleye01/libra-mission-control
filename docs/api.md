# Libra application API · slices 1–2

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

GZI, Dangote and CHI are initial client records, not generated shipment data. Only the GZI import mapping is reviewed/implemented in this slice. Attempting it for another client returns 422.

## Import lifecycle

| Method / route | Behavior |
|---|---|
| POST /api/imports/preview | Stage a CSV and return normalized records/findings; no shipment register changes |
| GET /api/imports | Batches, status, hash, reporting cut-off, client and reconciliation summaries |
| GET /api/imports/{id} | Saved preview including source rows, normalized dates, proposed stages and findings |
| POST /api/imports/{id}/apply | Require `{confirm_test_import:true}`; atomically apply once to the test register |

Preview body contains `client_id`, optional `report_date` in YYYY-MM-DD, and either a known `source_id` or `filename` plus `content_base64`. Duplicate source bytes/client reuse the existing batch. A different cut-off on a duplicate source returns 409 rather than changing the saved interpretation silently. Applied imports are immutable through this API.

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

`changes` accepts `bl`, `description`, `terminal`, `liner`, `handler`, `field_agent`, `sgd` (C Number/SDG alias), `container_size`, `container_count` (integer 1–100000 or null), `approval_by`, `dates`, `reconciled`, `awaiting_duty_receipt`, `rotation`, `release_coverage`, `invoices`, `closure`, `completed`. Unknown fields are rejected. Empty dates normalize to null; all others must be valid ISO YYYY-MM-DD. All choices start unknown when absent. Client cannot be changed through this update endpoint.

- `dates`: first-slice date keys except gate_out/warehouse, plus `draft_received`, `draft_approved`, `client_invoiced`. Gate-out/warehouse dates are derived from movement events once reconciled. Actual draft approval needs draft receipt and an approver, and cannot predate receipt. Final assessment date plus non-empty `sgd` clears requirements without changing approval history.
- `rotation`: `{status:unknown|not_requested|gotten, number:text}`; `not_requested` represents explicit nil.
- `release_coverage`: `{do:count|null, tdo:count|null, customs_release:count|null}`. Counts are cumulative owner-confirmed coverage for the same job; dates alone do not establish scope. Individual container identities are deferred.
- `invoices`: keys `shipping`, `additional`, `terminal`; each has `{request:unknown|not_requested|requested, received:date|null, payment:unknown|not_paid|paid, payment_date:date|null, rated_through:date|null, coverage, applicability:unknown|required|not_applicable, reason:text}`. Coverage is the matching key or `combined` for shipping/terminal. Payment date requires an explicit paid report. A receipt date does not set paid. These are separate factual fields, not a finalized requested/unpaid invoice status vocabulary. No amount/currency/due date is inferred.
- `closure`: keys `empty_returns`, `shipping_final`, each `{applicability:unknown|required|not_applicable, date:date|null, reason:text}`. Not-applicable decisions require reasons here and on invoices. Client invoice and ECD are date fields. Refunds are not a universal completion gate.

`duplicate_reason` acknowledges a distinct job matching an existing client/BL. Such jobs keep separate IDs. Use IDs for mutations; search is a lookup aid and may match multiple jobs.

`exception_reason` can retain an observed release/movement fact that conflicts with prerequisite evidence. It records the exception in history and leaves a current review finding. It never permits unknown/exceeded quantity totals, invalid dates, stale revisions or incomplete closure. Ordinary forward entries reject unsupported TDO or gate-out. Future movement dates are refused. Customs release is not required before TDO, only before gate-out.

A movement body includes `{kind:gate_out|warehouse, quantity:integer, date, revision, reason, command_id}`. Optional `supersedes` identifies an unsuperseded event on this job of the same kind; quantity zero is only valid for such a cancellation. An identical-looking active event returns 409 unless `confirm_duplicate:true` explicitly confirms a separate load. Corrections append rows, and all dependent totals and prerequisites are recalculated. Both kinds require quantity reconciliation and a known total; gate-out counts do not reduce warehouse-pending quantities. Superseded/cancelled rows remain in the detail history.

A follow-up body has `{key, status:open|awaiting_response, responsible, blocker, next_action, source, revision, reason, command_id}`. Keys are returned by calculated actions, plus `reported_blocker` for a custom next action. Empty custom next_action clears that custom item, retaining the audit event. Standard requirements disappear only when the underlying facts satisfy them; saved follow-up metadata remains in history. An empty responsible person stays unassigned unless a file handler is known.

Action objects include key, next_action, status, responsible, blocker, source, last_action_at and as_of; `/api/actions` adds client_name, bl, job_id, shipment_id and historical. Historical jobs use their report cut-off, or no age calculation if unknown; reconciled jobs use today's Africa/Lagos date. `as_of` overrides calculations for review only and never sends or reschedules anything. ECD dates from split delivery require an agreed anchor. Rating-expiry and twice-weekly closure schedules are not implemented.

Operational storage is separate from `import_rows`: `job_updates` holds versioned current facts, `movements` is append-only, `commands` supplies idempotency and `audit` records actor/reason/before/after/revision and movement payload. `source_snapshot` and import preview records remain byte-for-byte equivalent in meaning/content after edits. Schema upgrades preserve v1 IDs, sources and owner sessions and create a private SQLite backup first.

## Boundaries

No payment execution, deletion, notification-send, Hermes-shell or gateway-control endpoint is included. No arbitrary file path is accepted. Only the four explicit frontend asset paths are served; import originals, backups and application data are not static assets. Unknown routes return 404, known routes with another method return 405, and oversize requests return 413 before their body is read.

The owner can view/edit all clients; staff-specific roles remain deferred. Client filtering is applied on the server but is not presented as tenant authorization. Deployment is loopback-only; proxy hosts/TLS and additional access models require explicit future configuration. No live reminder activation or VPS change is implied.
