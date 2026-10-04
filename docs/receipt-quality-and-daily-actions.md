# Receipt quality, quicker sources and daily controls

Physical receipts now collect and buffer their pages before sending them. This
allows advisory quality checks before the text is sent, while the network printer
connection opens only after collection rather than sitting idle through API waits.
The normal paper-tidying cut still happens when hardware opens. Page order and
receipt contents stay the same. A failed collector can still produce its existing
error notice; uncaught generation errors do not send buffered pages. Printer
failures during transmission can still leave a partial paper receipt.

The checks flag text lines exceeding 42 columns, pages over 180 lines, possible
repeated delivery titles, cached/partial/unavailable sources and source checks
older than 24 hours. They are advisory: wide lines can wrap instead of clip, and
separate parcels can have identical names. Warnings appear in logs before text
transmission and in Preview / saved archive views. They do not verify actual paper
output or change task ordering. Archived receipts naturally become out of date.

## Calendar and delivery performance

Calendar downloads have connect/read limits, a bounded streaming body and a
12-second download budget checked between chunks. Recurrence parsing runs in a
separate disposable Python worker with an eight-second timeout. Killing/reaping
that worker prevents expensive calendars from blocking the receipt indefinitely.
The body limit is 2 MB, with at most 2,000 expanded events. Network DNS resolution
and OS scheduling can still extend observed wall-clock timings.

Gmail uses a five-second socket timeout, a twenty-second overall fetch budget
checked between messages, bounded 512 KB message bodies and a one-second logout
limit. It reads without marking messages as read. A completed search with no
notices is valid; errors are distinguished from empty results. If only part of
the mailbox was scanned, useful returned notices are labelled partial. Existing
local JSON fallback remains available.

Parsed results are cached privately for five minutes; raw emails, login details
and calendar feed URLs are not stored in the cache. Cache identities hash source,
local date and calendar range. Failed refreshes may use same-day results at most
24 hours old, clearly labelled on paper and in the web source checks. Original
source timestamps remain intact when cached data is used. Calendar / delivery
changes during the five-minute window appear on the next refresh. The diagnostics
page offers Refresh sources on next receipt, retaining fallback data.

`data/source_cache.json` contains personal event/delivery descriptions and is
owner-only, gitignored and excluded from configuration backups. It retains up to
12 source/range entries. Printer & source diagnostics shows the most recent
attempt duration and original source time, sorted by duration. It does not store
raw exceptions, request URLs or credentials.

## Interface controls

Quick actions brings due tasks, today's selected exercises, saved pending delivery
notices and a recipe selector together, with large mobile controls. Each action
returns to the same page. Existing Tasks / Deliveries / Meals pages retain history
and undo controls. It uses saved data and does not fetch a mailbox or generate a
meal plan just by opening it.

Finance → Review uncertain payments uses a private snapshot created during Finance
review. It lists uncategorised outgoing payments from the available 30-day bank
window and unmatched monthly commitments. Category corrections use the same
private rules file already used by receipt categories and web charts. Purchase
rules match date, merchant and amount; identical purchases on that date share a
rule. Merchant rules match the saved merchant text across payments. Category edits
never mark a bill as paid. Review its existing matching words/date/amount in account
settings, and refresh Finance to recalculate results. Queue records exclude bank
account IDs and tokens, remain gitignored and are not published. Rules are included
in private configuration backups, but the queue is rebuildable and excluded.

Printer diagnostics displays the configured connection/address, the last manual
TCP check and a short test-print button. Connection checks send no paper or cutter
commands. Test prints run through the existing authenticated, CSRF-protected print
queue and ten-minute supervisor; they respect receipt job locks. A reachable socket
is not evidence of paper, closed cover or successful paper output. The test receipt
itself makes no external source calls.
