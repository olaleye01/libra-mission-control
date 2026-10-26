# Libra Mission Control

A local test workspace for multi-client shipment visibility. This first slice includes owner access, client records, reviewed GZI CSV previews, explicit application to a test register, a searchable/filterable register, QAC findings, and shipment details with original values and provenance.

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
4. Build a preview. Inspect review findings and click any BL to see the normalized milestones and all original cells.
5. Select **Apply to test register** and explicitly acknowledge that this is a historical test import. Preview alone never populates the register.
6. Browse Overview, Shipments and QAC review. Search by BL, client, terminal, cargo, handler or SGD, filter by client/state, and inspect source/history in shipment details.

If supplied locally, `imports/sources/GZI-report-26-10-26.csv` is offered as a source without another upload. This private CSV is ignored by Git and is not part of the public assets. A checkout without private data still supports uploads and generated test fixtures.

Every accepted upload is preserved byte-for-byte in `data/originals/<sha256>.csv`. Imported snapshots retain physical CSV row, section, raw cells, normalized values and findings. Repeated BLs are kept as separate records. Re-uploading the same bytes for the same client opens the existing batch. Applying it again is idempotent. Existing applied records are never silently overwritten by a later upload.

## What the stages mean in this slice

The five labels are Awaiting arrival, In clearing, In delivery, Delivered and Completed. Imported stages are explicitly **historical proposals**, not verified live status. GZI's ATD column maps to actual berthing in Nigeria; other clients need reviewed mappings. A dated ECD can support a Delivered proposal, but it does not invent a delivery date or establish Completed. Partial-delivery notes are flagged; pending quantities stay unknown unless established by later operational entry.

DO, Customs release, TDO, gate-out and factory arrival remain distinct. The importer flags missing prerequisites and inconsistent dates while preserving reported facts. It does not certify release readiness or verify container coverage. A legacy assessment date is not treated as a client-approved final assessment, and receipt dates do not establish payment confirmation.

## Included / next

Included: local owner authentication, client creation, GZI previews and test imports, five-state views, search, filtering, pagination, source/history drawers, issue queue, audit events, original retention and persistent SQLite storage.

Next slice: manual milestone edits and corrections, delivery quantities/events, assessment approval versions, invoice coverage, completion controls and richer QAC resolution. Hermes chat/tools, Telegram writes, scheduled reminders, Odoo and additional client import mappings follow in later slices. Hermes profiles, routing, gateway services and credentials have not been changed. There is no live mode or outbound notification transport in this build.

## Checks

```bash
python3 -m unittest discover -s tests -v
node --check frontend/app.js
```

Tests use temporary storage and ephemeral loopback ports. They cover importer mapping, duplicate preservation, historical status evidence, partial delivery, release gaps, counts, malformed files, authentication, origin/Host checks, CSRF, file boundaries, repeated imports, confirmation, persistence, client filters and audit history. Real-source reconciliation is skipped if the private CSV is not available.

See `docs/api.md` for the lightweight API contract. Private planning notes, verification screenshots and client reports remain local and are excluded from the repository.
