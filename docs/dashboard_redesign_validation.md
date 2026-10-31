# Libra Circle dashboard redesign

## Brand and scope

The owner requested a full visual revamp using Libra Circle’s website branding while retaining the current typography. The official transparent logo and icon are bundled unchanged:

- Logo: https://libracircle.com/images/LOGO%20png.png
- Icon: https://libracircle.com/images/logo-3%20%282%29.webp
- Palette source: https://libracircle.com/css/style.css

The public CSS supplies navy `#131E3A`, gold `#D4A017` / hover `#BB8E12`, and blue `#173D8D`. The logo artwork uses gold `#E2AB24`. Georgia headings and the existing system sans-serif UI stack remain. No external fonts, image generation, application frameworks or hosted publication were introduced.

The shared style system covers the navigation shell, collapsed rail, overview, lifecycle cards, automatic-tracking status, coordination desk, shipment register, QAC, imports/previews, client directory, forms, shipment drawers, source history, sign-in and mobile layout. Tracking and queue panels share a workbench above the full-width register. Primary gold buttons use dark text; light-surface hover links use a darker gold for legibility.

## Executed checks

- `python3 -m unittest discover -s tests -v`: **140 tests, OK, one private-source fixture skipped**.
- `node --check frontend/app.js` and `git diff --check`: passed.
- Added HTTP coverage for the two fixed brand-image routes: exact binary bytes/MIME, GET-only access, and private/unlisted-path refusal. The normal service returned the official logo with HTTP 200 and `image/png`, matching the bundled bytes.
- Desktop browser QA verified the populated overview, sidebar collapse/expand, source import preview and mapping summary, client directory, QAC table and shipment detail form. A delivery-location update saved correctly in the isolated QA database and reappeared in the job summary.
- Phone browser QA at 390px verified overview/client layout, document width equal to viewport, hidden/inert navigation, menu open/background inert state, Escape close and focus restoration. Temporary viewport sizing was reset.
- A read-only source review identified two tablet-specific layout issues; the queue specificity and heading/action stacking were corrected. A later 768px live override did not apply to the test tab, so the final tablet correction is source-reviewed rather than claimed as a successful tablet browser screenshot.
- Small-text contrast issues in warning/tracking/test badges, inactive tabs, sidebar mark and hover links were corrected without changing the brand palette.

The company page’s browser-opening permission was declined; the owner then explicitly approved downloading only the public logo and CSS. No website JavaScript was run. A separate unauthenticated QA origin was also declined, so sign-in styling was source-reviewed but not browser-verified; no alternate browser route was used to obtain that view and no credentials were changed.

## Boundaries

The normal service remains loopback-only at port 8800. No normal shipment records, source snapshots, staff permissions, Hermes state, routing or notification policy were changed. Browser-save QA used a separate data directory. The public asset allowlist was extended by exactly two known images, with no general filesystem-serving route. Private screenshots remain ignored under docs/screenshots.
