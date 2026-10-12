# Receipt and interface quality

## Weather and sizing

Weather retains its drawing, all 24 hourly readings and the temperature graph.
The TODAY summary remains below the location, separated by a dashed line, and the
graph remains above hourly weather. Sunrise/sunset labels now match the order of
the displayed times. The hourly table labels temperature, humidity and wind units;
`>` marks the current reported reading hour (using the weather observation time,
or the London clock when that timestamp is absent).

`receipt/profile.py` owns the text column count and default printable pixel width.
Rendering, quality checks, captures, printer facades and the web receipt column
share those values. The web column still aligns full-width graphs with the dashes.
Weather renderers accept explicit `WeatherDependencies` and work without private
configuration or the live pipeline. Existing `_context` callers have a transitional
adapter. Weather labels/drawings and printer text helpers are separate pure modules.

## Finance edits and observation records

A bank refresh no longer reloads Finance over unsaved form edits. Instead it shows
a new-data notice and lets you explicitly load the updated review, discarding the
unsaved edits. Submitting a settings form proceeds normally. Leaving with unsaved
edits has the browser's usual protection. If refresh fails while edits are pending,
bank-derived forecast outputs are hidden while the inputs remain available.

Review calculations and page rendering do not save monthly observations,
reconciliation queues, payment explanations or local valuation observations.
Successful background refreshes record them through a separate callback. A failed
bank refresh does not record observations; an observation-write failure leaves
fresh bank data available and reports that history could not be updated. Explicit
monthly-review and settings-save actions retain their existing behaviour.

## Archive storage and retention

The archive shows receipt count, disk usage and pinned count. Keep all is the
default. You can select automatic deletion of unpinned receipts older than 30, 90,
180 or 365 days, or apply that selected policy immediately. Cleanup is permanent;
private settings backups do not contain archived receipt files.

Pinned receipts, damaged files, symlinks and records with ambiguous dates are
preserved. Valid expired unpinned records are removed at most once per day by the
existing maintenance worker. Pinning and cleanup share a lock. Preferences and pin
IDs are owner-only, excluded from Git, and included in private settings backups.

## Integration boundaries

`services/mail_source.py` now owns bounded Gmail collection, header/body parsing
and delivery classification. The pipeline retains compatibility functions and its
fallback-status flag. The collector still observes time/download limits and closes
the mailbox on failures. New error events omit exception text and credentials.

This checkout uses the already-separated Ticketmaster service for gigs. It has no
Spotify artist collector to extract; Spotify remains a spending category.

## Regression checks

`python tools/check_receipt_visuals.py` compares committed reference PNGs for a
weather receipt and a full four-page fixture. Weather and finance use their actual
renderers; Actions/Food use the existing illustrative sample pages. The fixtures
use fixed dates and example values, with no credentials, external calls or printer.
Only use `--update` after reviewing an intentional visual change. CI checks the
references on Python 3.12 to keep the rendering environment consistent.

Browser fixtures also check graph/text edge alignment at four screen sizes,
unsaved finance edits, archive controls and keyboard focus through the skip link.
Axe checks WCAG 2 A/AA and 2.1 AA rules, including names/labels and contrast, on the
main fixture pages. These automated checks complement manual usability checks;
they cannot prove accessibility of every possible user-provided content item.
