# Automatic MSC tracking validation

Current scope: automatic carrier discovery, persistent scheduling, safe operational updates, automatic empty-return stopping, overview exceptions and read-only history. The earlier setup/authorisation/reason/paste workflow has been removed from the dashboard.

## Executed checks

- Full suite: `python3 -m unittest discover -s tests -v` — 139 tests, OK with one private-source fixture skipped.
- `node --check frontend/app.js`, Python compilation and `git diff --check` passed.
- Twelve automatic-worker tests use synthetic pages. They cover first-check discovery without setup, 08:00/16:00 Lagos schedules and restart persistence, source-owned ETA changes, owner correction/change-back and explicit clears, reconciled import updates preserving original snapshots, historical test exclusion, reason-free retry, cross-worker SQL claims, count conflicts, retained success after more than 20 failures, overview scope, backoff and legacy finished monitors.
- Ten collector tests cover specific denial/challenge diagnostics, generic reCAPTCHA disclosures, supported Nigerian port discovery and expansion of closed visible container histories. The expansion script was executed against a DOM double with hidden/visible alternative plus icons; no hidden application state is read.
- Separate browser QA used an injected synthetic collector. Two new synthetic MSC jobs were enrolled and checked without opening a job or submitting any tracking setup. One was updated and finished automatically after complete empty-return coverage. The other retained an owner ETA and surfaced the conflict on the overview. The source was synthetic; this is not evidence of successful live unattended collection.
- Browser checks confirmed there are no tracking setup, lookup-reason, capture or routine review forms. Summary contains automatic progress and history; overview exposes scoped exceptions. No warehouse delivery or clearing-job Completed state was inferred.

## Live source result

One bounded automatic check of an already owner-authorised MSC sample in the isolated QA workspace returned a genuine **Access Denied** page before BL submission. The collector recorded `error_code:access_denied`, phase `navigation`, title `Access Denied`, and bounded page text. This distinguishes confirmed denial from the former overly broad CAPTCHA-word heuristic. No bypass, fingerprint spoofing, alternative identity or hosted scraper was attempted. The persisted next attempt uses the long backoff. Live unattended MSC availability is unresolved on this machine; scheduler and synthetic checks must not be presented as proof that it works.

## Normal local workspace

The loopback service at port 8800 was restarted with automatic scheduling enabled. Its existing 14 active shipments remain unchanged. All currently imported test records are ineligible for live collection: there are zero normal tracking configurations and zero normal tracking checks. Owner access remains configured, and the public session health endpoint returned OK. Hermes, credentials, Telegram routing, notifications and VPS deployment were unchanged.

The separate browser QA workspace runs at port 8822 with injected responses and an explicit synthetic BL scope. It is not the normal dashboard or a production data source. Browser screenshots and real MSC evidence remain private ignored files.

## Operational limits

The worker needs the application process to be running, persistent application storage and an installed sandbox-capable Chrome/Chromium. It is an application scheduler, not an OS cron installation. Other shipping lines need their own reviewed connectors. Unknown facts and unsupported event shapes remain evidence/errors; no quantities, releases or regulatory decisions are inferred. Source changes conflicting with owner corrections stay exceptions. Finishing carrier tracking is distinct from completing the job.
