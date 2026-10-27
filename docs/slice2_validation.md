# Slice 2 validation

Implemented locally on 2026-10-26. This record covers execution against isolated application storage and the local loopback service. It is not a deployment, independent Elephant-Goldfish review, Hermes integration or reminder activation claim.

## Delivered

Manual jobs for all clients; immutable import snapshots plus separate owner updates; optimistic revisions and idempotent commands; final-assessment receipt/C Number requirement clearance; actual draft approval history; separate invoice request/receipt/payment/rating/applicability; combined invoice coverage; explicit release counts; append-only gate-out/warehouse events and corrections; full delivery/completion checks; internal follow-ups and awaiting-response metadata; before/after audit history; v1 migration with SQLite backup.

## Executed checks

- `python3 -m unittest discover -s tests -v`: **34 tests passed**, including the available private-source reconciliation. Temporary databases and loopback servers only. New acceptance cases cover duplicate BL acknowledgement, idempotency, concurrent/stale edits, rollback, assessment pair/either-alone behavior, duty completeness, nil/unknown/unpaid distinctions, combined invoices, release ordering/count coverage, partial movements, duplicate loads, corrections/cancellations, reported exceptions, completion applicability, source immutability, calendar boundaries, split ECD anchor, persistence and v1 backup/migration.
- `node --check frontend/app.js`: passed.
- `python3 -m compileall -q server tests`: passed.
- `git diff --check`: passed.
- Browser checks in disposable storage at `/tmp/libra-slice2-browser-qa`: created a synthetic Dangote job, saved assessment/release counts, entered four gate-outs and two warehouse arrivals, observed two pending, saved a combined invoice with different payment/rating dates, retained a duty follow-up as awaiting response, inspected audit events. No browser warning/error console entries.
- Desktop layout and a 390 × 844 viewport checked. Mobile body width 390, dialog client/content width 375, movement form one column with no unintended horizontal document overflow. Tabs scroll intentionally. Temporary viewport reset after testing. Private screenshots are in ignored `docs/screenshots/`.
- Main local service restarted at `127.0.0.1:8800`. Before/after counts match: three clients, zero shipments/batches, one owner session, one owner credential setting, two audit records. Migrations 1–3 applied; foreign-key check empty; one private pre-upgrade backup created under `data/backups/`. The normal register was not seeded with QA shipments.

## Browser-test isolation finding

Although the QA database was separate, cookies are scoped by hostname rather than port. Signing in at 127.0.0.1:8811 replaced the browser cookie for the normal app at 127.0.0.1:8800. The main tab therefore needs the owner's normal sign-in again. The owner credential and original server session record were preserved; no password was read or changed. Future QA must use a distinct hostname (for example localhost for QA and 127.0.0.1 for the main app) or an isolated browser session, as well as separate database storage.

## Limits retained

All shipments remain test records. Release coverage is owner-reconciled cumulative count scope, not independently verified container identities. Detailed staff roles, full QAC issue-resolution workflows, attachments, final unpaid-invoice terminology, rating-expiry trigger definitions, split-delivery ECD anchor selection, closure weekdays, Telegram/Hermes adapters, outbound reminders and VPS deployment remain separate work. No payment, provider/client/field-agent contact, declaration submission or Hermes state change occurred. No Git commit/push is included in this slice.
