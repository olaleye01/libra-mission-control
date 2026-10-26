# First-slice API

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

## Shipment visibility

| Method / route | Behavior |
|---|---|
| GET /api/overview | Counts by proposed state, warning counts, known container count/unknown coverage, mode and connection availability |
| GET /api/shipments | Paginated records, excluding raw cell arrays |
| GET /api/shipments/{id} | Full record, raw cells, source provenance, normalized dates, findings and application import history |
| GET /api/audit | Most recent 30 application events |

Overview/list filters: `client_id`. List additionally supports `search`, `state`, `issues=1`, `page` and `limit` (maximum 100). Shipment IDs are application-generated integers, displayed as LMC-00001 etc. BLs and source serial numbers are not unique identifiers. Internal job IDs are created only when a preview is applied; previews use source-row references.

`proposed_state` and `review_status` distinguish historical interpretation from verified operational state. `pending_count` remains null because the source does not supply reliable event-level quantities. Imported records never infer Completed. Date fields include pre-alert, ETA, berth, PAAR, OBL, legacy assessment, duty receipt, exam, Customs release, DO, TDO, gate-out, warehouse arrival, terminal validity and ECD.

## Boundaries

No milestone-write, payment, shipment deletion, notification-send, Hermes-shell or gateway-control endpoint is included. No arbitrary file path is accepted. Only the four explicit frontend asset paths are served; import originals and application data are not static assets. Unknown routes return 404, known routes with another method return 405, and oversize requests return 413 before their body is read.

The owner can view all client records; staff-specific roles remain deferred. Client filtering is applied on the server but is not presented as tenant authorization. Deployment is loopback-only; proxy hosts/TLS and additional access models require explicit future configuration.
