# Flexible GZI import validation

Implemented locally on 2026-10-27 (Africa/Lagos). GZI now uses heading aliases rather than requiring the previous 34-column layout. New previews retain actual source headers/raw cells and distinguish missing columns, blank values and values needing interpretation. Repeated headings remain ambiguous; no duplicate Gate Out Date column becomes warehouse arrival automatically. Each section can have different columns. Missing source information is not a claim that a document is operationally outstanding. Existing saved batches are unchanged.

Executed verification:

- 43 tests pass, including original-source 220-row/219-BL reconciliation, the reduced 27-column/five-shipment source, minimal/reordered sheets, section changes, placeholders, short rows, extra cells, duplicate headings, data containing heading words, preview/application persistence and all prior operational/access tests.
- JavaScript syntax check, Python compilation and git diff whitespace checks pass.
- Browser preview in isolated storage at localhost:8812 shows five records, both section mappings, and expandable mapped/pending/unmapped columns. No console warnings/errors. Nothing was applied to the normal register. A different hostname from the normal app protected its browser cookie.
- Main local server restarted on 127.0.0.1:8800 with the updated importer. Isolated QA server stopped afterward. No schema migration, Hermes/routing change, reminder, external contact, deployment or Git push.

Private preview evidence is retained in ignored docs/screenshots/flexible-import-preview.png. The real CSV remains private/ignored. Client-specific mappings beyond GZI remain deferred.
