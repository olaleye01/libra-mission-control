# Pending warehouse input validation

Implemented locally on 2026-10-27, Africa/Lagos. Update job now includes an editable Pending warehouse input, actual arrival date and optional warehouse-event correction selector. The value reconciles active movement history, rather than creating an independent balance or overwriting source reports.

Verification:

- All 63 unit/API tests passed, including the prior 54 regressions and nine new delivery-balance cases. Covers partial/full arrivals, unknown/invalid totals, real dates, release evidence, explicit holds, corrections/cancellations, duplicate confirmation, idempotency, stale revisions, immutable imports, closure gates and atomic rollback of unrelated job edits.
- JavaScript syntax, Python compilation and Git whitespace checks passed.
- Isolated localhost browser QA started with a four-container job and four recorded gate-outs. Changing pending to two with an actual arrival date recorded two warehouse arrivals. Correcting that arrival to one container changed pending to three and retained the original superseded two-container event. The field and correction option were visible in Update job. No browser console warnings/errors. Screenshot remains private under ignored docs/screenshots/pending-warehouse-input.png.
- Normal loopback service restarted with existing application storage. Source records, saved operational data, movements, sessions, settings and audit contents were checked against their pre-restart fingerprints. No real-shipment write, source rewrite, schema migration, outbound message or Hermes change was part of QA.

Current scope remains a local test workspace. The initial validation preceded the Git commit.

Update on 2026-10-28, Africa/Lagos: the owner deferred the warehouse balance controls and quantity-reconciliation checkbox, so they are now hidden in Update job. The API and movement history remain supported. Isolated browser QA confirmed ordinary edits preserve saved reconciliation status without creating movements. Client approval date/approver inputs are also hidden; a separate QA save preserved earlier approval entries. The latest complete suite passed all 67 tests, and JavaScript syntax and Git whitespace checks passed.
