# Reviewed report updates

The importer now offers a client/BL match review before changing the active register. Original import rows stay immutable. Unique matches keep the job ID, new BLs create new jobs, and ambiguous/repeated matches block application. Blank or uninterpretable values preserve earlier information, and independent owner edits survive three-way source comparison.

Validation: all 79 unit/API tests passed, including 12 report-update cases for matching, sparse files, owner overrides, repeated BLs, client isolation, stale reviews, replay safety, duplicate archival, independently edited duplicate protection, older cut-offs, release/count conflicts and BL punctuation. JavaScript syntax, Python compilation and Git whitespace checks passed.

Isolated browser QA used synthetic reports containing an original job, a duplicate from an updated report, and a new BL. The review showed one job update, one already-linked row and one duplicate archive. Applying kept the original job ID, owner cargo description and destination, added the new berth date, preserved ETA, reduced the active count from three to two, and retained both report versions in Source & history.

Local existing-data reconciliation was backed up with SQLite's backup API before changes. Duplicate source rows remain physically stored and are excluded from active views through explicit alias records. Original source rows, shipment rows, movements, owner credentials and sessions remained unchanged. Existing assignment, invoice, task, approval and reconciliation data was checked against the normalized prior record. No outbound communication, payment, declaration, Hermes change or deployment occurred. Private screenshots and backups remain ignored by Git.
