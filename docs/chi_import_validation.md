# CHI import validation

The owner confirmed these report meanings: COUNT COUNT is container count; Duty Pay Date is duty receipt received; ATA is actual berthing for sea shipments; TDO / Exit Note Date is TDO for sea and an exit note for air. The later duty-receipt correction supersedes the earlier payment-only interpretation.

Implemented client-scoped chi-header-v1 aliases for BOL/AWB NO, PAAR/OBL Recd Date, COUNT COUNT, KG/SIZE, Duty Pay Date, Custom Exam Date, Custom Rel. Date, TDO / Exit Note Date and AGENT. Non-sea/unknown transport modes retain raw arrival/exit-note and weight/count evidence for review instead of converting it to sea release milestones or container quantities. No regulatory-authority requirements are inferred.

All 89 unit/API tests passed with the private CHI fixture supplied, including ten CHI tests. Tests cover owner-confirmed dates/counts, sparse/reordered headings, ambiguous headings, invalid dates, mode safeguards, client isolation, immutable source preservation, preview/apply and same-job report revisions. JavaScript syntax and Git whitespace checks also passed.

The supplied CHI report produced five distinct SEA shipment proposals. Its source headings and all 27 cells per shipment remain preserved. Browser verification showed the CHI mapping and five-row preview. Only a preview was prepared in the normal workspace: existing shipments, operations, movements, report-update links, aliases, credentials and sessions were fingerprint-checked unchanged, and all earlier import rows were compared unchanged. No automatic application, messages, payments, Hermes changes or deployment occurred. The private fixture, original CSV and screenshot remain outside source control.
