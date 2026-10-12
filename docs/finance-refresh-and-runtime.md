# Background finance retrieval and operational checks

Finance opens immediately from the last bank snapshot, or shows a lightweight
retrieval page on first use. A background worker fetches transactions and balances;
the browser polls small, authenticated status messages and reloads when the new
snapshot is ready. Opening Finance within 30 minutes reuses its bank snapshot.
The Refresh bank data button always requests a new check. Local forecasts and
settings are recalculated when the review is rendered.

The retrieval panel shows bank/provider stages and recent stage timings. Browser
status polling never reads the transaction payload. Without JavaScript, retrieval
still runs; reload the page to view its result. Workers coalesce repeated refreshes
using an installation file lock, including across web processes. Network calls
retain their 20-second timeout; the session stops starting new calls after ten
minutes. The final in-flight call can take up to its own timeout to finish. Stopped
workers are detected from their start time, and failed automatic retries are held
for one minute; a manual refresh can retry immediately.

## Freshness and privacy

Snapshots live in `cache/finance_review`, an owner-only directory with owner-only
files. The existing Git ignore rules and private backup allowlist exclude this
cache. It contains bank transactions and balances, **never access/refresh tokens**.
Clear this directory to remove cached bank data; Finance fetches it again on use.

A failed refresh retains the previous snapshot and labels it as previous data.
Snapshots older than 30 minutes, from an earlier London calendar day, or following
a failed refresh cannot provide a fresh forecast. Their numeric forecasts are
withheld, and stale data is not captured as a new finance observation or payment
reconciliation. Partial transaction coverage also keeps forecasts withheld.
Changing selected accounts or transaction-source scope invalidates the snapshot.
Source changes during retrieval prevent publication of that result.

One scoped bank session is shared by transactions and balances in the live web
review, test-finance collection, and live finance printing. It refreshes each bank
connection once and reuses its account/card inventory. Balances and transactions
are not cached within the HTTP helper. A new session makes fresh requests. Token
rotation is locked across the complete read/refresh/write operation, including
other processes; tokens are re-read under the lock before refreshing. A failed
connection is not repeatedly refreshed within the same session.

## Module boundaries and logs

- `services/bank_transport.py`: TrueLayer authentication, reads and date-range
  fallback. Existing pipeline helpers remain compatibility wrappers.
- `services/bank_session.py`: scoped reuse, deadlines and collection orchestration.
- `web_control/finance_refresh.py`: private snapshots and background worker state.
- `web_control/finance_review.py`: finance review rendering and editing routes.

Integration logs use small JSON events with operation, provider, elapsed seconds,
status, error class and optional HTTP status/count. Authentication responses,
transaction payloads, account IDs and exception text are not logged by these new
banking events. Public-source collection also records completion/failure duration.
Existing source health and receipt timing displays remain available.

## Validation and CI

Regression coverage checks one refresh/inventory request per provider in a shared
session, failed-refresh preservation, cross-worker refresh coalescing, source
selection changes, private file modes, stale-data handling, and authenticated/CSRF
refresh endpoints. Forecast invariants cover 54 combinations of salary, debt,
strategy and daily spending, plus different account counts and penny-sized
allocations. Browser fixtures exercise first retrieval, refresh and failed refresh
without any external bank request, alongside existing forms and responsive layouts.

CI runs on pull requests and main pushes, cancels superseded runs, and bounds
Python jobs to 15 minutes and browser jobs to 10 minutes. Each coherent update
continues to use a squash merge.

## Measure your Raspberry Pi

Run these commands on the actual Pi, using the project's Python environment:

```sh
python tools/benchmark_hot_paths.py --iterations 3
python tools/benchmark_runtime.py --iterations 3
python tools/benchmark_runtime.py --include-web --iterations 3
```

The runtime tool measures fresh-process import time, whole-process startup time
and peak resident memory. It reports the machine architecture and Python version.
`--include-web` imports the configured web app and requires its existing local
secret key; it does not launch a server, retrieve bank data or access the printer.
A missing dependency/configuration is reported by error class. Neither benchmark
modifies application data; synthetic workload files are temporary.

Compare runs on the same device/Python version. Keep live retrieval timings
separate from synthetic measurements: bank response times depend on the provider.
The current development measurements are Linux x86-64 results, not Pi results.

Finance now preserves unsaved edits when new bank data arrives. Viewing cached
reviews is read-only; successful refreshes record observations separately. See
[Receipt and interface quality](receipt-interface-quality.md).
