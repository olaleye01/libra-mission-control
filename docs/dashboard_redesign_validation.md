# Libra Circle dashboard redesign

## Overview layout and real data, November 2026

The owner approved the layout/data stage of the globe reference before animation. The Overview now pairs a compact Officer's briefing and clearing snapshot above its existing five lifecycle filters and five-job register. A separate rail contains team queues, truthful carrier status and priority attention jobs. Two attention jobs appear initially; the remaining returned jobs stay in a disclosure. Recent imports follow the selected client, and connection details sit in a small disclosure. No globe, route illustration, trend chart, carrier ranking or unconnected external feed was added.

The API builds briefing/attention summaries from the existing workflow and scoped records. Briefing counts actions while previewing different job IDs. Explicit active holds and reported blockers precede review questions; a blank source field does not establish a missing document. Historical cut-offs remain dated or unknown, and unreconciled manual jobs are not labelled historical imports. Briefing links open the correct job and preselect its follow-up or coordination entry.

`python3 -m unittest discover -s tests -v` ran 148 tests: 147 passed and one private CHI fixture skipped. Seven new acceptance tests cover scope, assignments, distinct-job limits, repeated BL IDs, resolved items, historical/manual provenance and read-only aggregation. JavaScript syntax and Git whitespace checks passed. Taste source lint reports zero failures and 18 warnings for scope labels, actual overlays, existing welcome sequence numbering and existing dash usage. The existing welcome-scene lighting and WebGL alpha mask have explicit, explained lint exceptions; their appearance was not changed in this slice.

Browser checks used the existing owner workspace without saving shipment changes. Desktop checks verified totals, client-only briefing/imports, stage/search/client preservation through View all, and selecting the ECD follow-up from a briefing link. At 1440px the register and all three rail headings are visible in the first 900px. At 390px, job cards remain readable, the snapshot follows the register, scrolling strips stay inside their frames and the first shipment begins around 586px. The document did not overflow horizontally. A later browser session returned to sign-in, so additional phone navigation and tablet visual checks were not completed; no authentication code was changed. Temporary viewport sizing was reset. Owner configuration and shipment/source table fingerprints remained unchanged; the owner's sign-in changed only sessions. Screenshots remain private and ignored by Git.

## Welcome diorama, November 2026

The owner requested a darker, more dimensional port illustration while retaining the ship-to-warehouse flow. The welcome panel now uses a local native-WebGL renderer with shaded vessel, crane, container, forklift, truck and warehouse models; cyan rim details; a fitted isometric camera; and the same 24-second journey. The original animated SVG remains a fallback. A pause button works with either renderer, reduced motion starts still, and rendering stops when the welcome panel or page is hidden. No shipment facts, remote assets or new runtime dependencies are used.

Browser QA used a temporary page containing only the decorative scene, with no sign-in form or application data. The 3D scene rendered successfully, screenshots showed the ship, terminal and truck phases, the pause frame stayed byte-for-byte unchanged across successive captures, and the control resumed the loop. The scene fitted a 390px viewport without horizontal overflow and the browser reported no console errors or warnings. The full sign-in layout was source-reviewed; the owner's signed-in dashboard was not logged out for this check.

`python3 -m unittest discover -s tests -v` ran 141 tests, with 140 passing and one private-source fixture skipped. The new fixed script route is covered for exact content and GET-only access. JavaScript syntax and Git whitespace checks passed. A focused no-WebGL check verified fallback pause and reduced-motion default handling. The local application returned HTTP 200 for the new script after restart; existing shipment/source and owner-session table fingerprints were unchanged.

## Taste refresh, November 2026

The later refresh applies Taste's Achromatic ledger direction (seed 1855407489), retaining the official mark, palette and existing type. The two dealt shell options were redrawn or adapted because the owner needs named client and department navigation and a collapsible sidebar. The current layout uses a light labelled sidebar, an Import Officer briefing, a proportional five-stage filter strip and a five-row register preview alongside coordination and carrier status. A full-register link preserves the current client, stage, search and review filters. Additional carrier exceptions remain accessible in an expandable list. Unknown quantities remain unknown, and no shipment counts are fabricated.

Browser checks used an isolated test workspace at 1440, 768 and 390px. They confirmed stage filtering, preserving stage and search filters when opening the full register, opening a job on desktop and phone, tablet navigation and Escape, desktop sidebar collapse/expand, and the import and QAC screens. The viewport did not overflow horizontally in the measured phone and desktop views. The first phone shipment begins at approximately 686px in an 844px viewport; the five-stage and client strips scroll within their own frames. The sign-in layout was visually checked with the disposable QA account.

`python3 -m unittest discover -s tests -v` ran 140 tests successfully with one private-source fixture skipped; `node --check frontend/app.js` and `git diff --check` passed. A focused local check confirmed that three carrier exceptions each retain a direct job link. Taste source lint reported zero failures and 13 warnings: scope/status labels, shadows on actual overlays, and dashes used in existing interface copy and unknown values. Taste's separate CDP inspector was not run; responsive checks used the in-app browser instead. Screenshots are private and use test data.

## Earlier branding refresh

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
