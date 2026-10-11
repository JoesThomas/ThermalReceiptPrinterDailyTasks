# Repository cleanup and performance — 11 October 2026

The review covered all 157 Python source files, the web JavaScript and templates,
collector/storage boundaries, meal planning and the published Git history. It
used local synthetic data rather than bank, email, calendar or printer access.

## Changes

- Shared ESC/POS text cleaning and rail-time parsing replace duplicate bodies;
  safe plain ASCII takes a short path through the text cleaner.
- Google Docs identifiers/export URLs and private configuration loading are
  shared. Importing the standalone document printer no longer imports the whole
  live pipeline or reads credentials; printing loads its configured URL on demand.
- State files share one sidecar-lock helper. Optional dashboard/setup JSON reads
  share a tolerant helper; strict stores retain their schema validation.
- Weather and enabled news sources are collected in a pool of at most four
  workers. Their existing bounded downloads and stale fallbacks stay in place.
  Printing stays ordered, and one failed source does not discard successful ones.
- Category rules are prepared once per analysis batch, including dated private
  overrides. Current/baseline windows share one transaction pass; rule priority,
  rent word boundaries and Decimal totals remain consistent.
- Wealth history groups records by account once instead of rescanning all records
  for every account. Meal selection chooses the highest score without sorting the
  whole candidate pool; score evaluation order and first-candidate ties are kept.
- Archive browsing renders 50 matching receipts at a time. A bounded in-process
  cache retains listing/search text, not images or scenario payloads. File metadata
  invalidates changed/replaced receipts; deleted receipts are absent from listings.
- The finance collector dependency adapter is shared. The earlier delivery-date
  definition, overwritten by a later definition, has been removed.

## Reproducible synthetic measurements

Two runs per case on the same local Python 3.12 environment, before/after this
change. Result hashes match in every case. These measurements describe these
fixtures, rather than live provider response times or a Raspberry Pi benchmark.
The archive first-page average includes its initial cache population.

| Case | Before | After |
| --- | ---: | ---: |
| Trends: 10,000 transactions, 100 private rules | 1,104 ms | 35 ms |
| Wealth history: 200 accounts, 10,000 valuations | 193 ms | 21 ms |
| Clean 10,000 printable ASCII lines | 59 ms | 2 ms |
| First archive page: 300 receipts with image payloads | 52 ms | 7 ms |
| Repeat archive page | 50 ms | 1.4 ms |
| Four independent collectors with 20 ms simulated latency each | 80 ms | 21 ms |

Run `python tools/benchmark_hot_paths.py` to reproduce the fixtures. To compare
an older checkout, pass `--source-root /path/to/older/worktree`. The benchmarks
write only temporary fixture files and do not alter saved application data.

## Scope and remaining boundaries

Compatibility facades remain for existing callers. Separate finance policies,
strict-versus-optional parsing and different cooking views are not interchangeable
just because they contain similar expressions. The large legacy pipeline remains
an orchestration facade; future extraction should follow the existing modular
collectors/renderers rather than a wholesale rewrite.

Bank token refresh and related calls have not been parallelised further: their
shared authentication state needs its own concurrency design. Calendar travel
chains retain their event ordering. Archive text searches may still scan many
files on their first run, while unfiltered initial browsing reads only one page.
