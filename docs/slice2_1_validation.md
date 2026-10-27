# Slice 2.1 validation

Implemented locally on 2026-10-27 (Africa/Lagos). This validates software behavior, not real-shipment status, regulatory compliance, deployment, Hermes integration or an independent Elephant-Goldfish review.

## Delivered

- Import Officer and Field Agent are separate. The source File Handler maps to Field Agent; Import Officer initially defaults to Owner. The handler API key remains a compatible alias. Raw reports and saved source snapshots stay unchanged. Reads normalize older operation records without writes; conflicting old assignments and saved people without a team remain visible for review.
- Import Officer(s) are shown once in the persistent job detail header; the shipment table lists only the Field Agent.
- Import Officer desk with client/team/status filters and five overlapping queues: My next actions, Awaiting responses, Clearing blockers, Delivery progress and Closure. Overview links to the queues.
- Responsible team/person and reminder recipient are separate. Calculated follow-ups default to the officer. Team assignments are coordination metadata, not staff access permissions. Reminder recipient stays Owner and sending is disabled.
- Manual coordination items for Import Officer, Field Agent, Accounts, QAC, Regulatory and Unassigned. Title, next action and source are required. Authorities are only manually supplied; no authority-specific rules or obligations are inferred.
- Open/in-progress/awaiting-response/resolved workflow. Resolution requires note/date; reopening preserves earlier resolution history. Multiple items per job use its shared revision, command idempotency and before/after audit.
- Optional owner-selected holds apply to TDO, gate-out, warehouse arrival or completion only. Observed-fact exceptions can retain reported release/movement facts while leaving holds open. Completion holds cannot be bypassed. Historical gaps do not prevent recording coordination about them.

## Executed verification

- `python3 -m unittest discover -s tests -v`: **54 tests passed**, including all earlier operational/import/access regressions. New cases cover role aliases, defaults, raw source preservation, read-only normalization of old records, conflicting assignments, responsibility/recipient separation, manual regulatory items, resolution/reopening/history, client/team/queue filters, explicit holds, completion constraints, persistence, stale edits, idempotency, cross-job isolation and owner/CSRF authorization.
- `node --check frontend/app.js`, Python compileall and `git diff --check`: passed.
- Browser QA used isolated application storage and the localhost hostname, separate from the normal 127.0.0.1 app/cookie. Created a synthetic shipment with separate roles, created and assigned a Regulatory issue, assigned a PAAR follow-up to its Field Agent while retaining Owner as reminder recipient, checked queues and team filters, edited an item, and resolved it with note/date. No browser console errors/warnings.
- Desktop and 390 × 844 mobile layouts checked. Mobile queues use two columns; sidebar retracts and document width stays within the viewport. Temporary viewport override reset. Private screenshots are ignored under docs/screenshots/slice21-desk-desktop.png and slice21-desk-mobile.png.
- Normal local service restarted on 127.0.0.1:8800. Row counts and content digests of clients, shipments, batches, import_rows, job_updates, movements, sessions, settings and audit matched before/after restart; no foreign-key violations. No automatic database migration or source/credential rewrite was required.

## Boundaries

No real shipment was verified or updated by QA. Detailed Regulatory processes remain deferred until supplied. No outbound messages, payments, authority submissions, staff login changes, Hermes/routing changes or VPS deployment. Work remains local until an explicit commit/push request.
