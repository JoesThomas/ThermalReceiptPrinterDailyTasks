# Codebase review — 2 October 2026

Reviewed the Python application, web routes/templates, collectors, receipt capture,
finance calculations, local storage and project setup. Ran the existing suite,
compilation, undefined-name/duplicate-definition checks, Bandit security analysis
and a request-timeout/authentication inventory. No real bank, email, calendar,
printer or personal credential files were used for verification.

## Fixed

- The regular-payments text parser used its payment type before assigning it.
- Future Tasks receipt requests were discarded when settings were reloaded because
  their key was absent from the default settings schema.
- Offline CLI previews/validation/health checks imported live hardware/API dependencies.
- A Google Docs request had no timeout. All Requests calls now specify one.
- External RSS XML now rejects DTD/entity declarations and oversized parsed feeds.
- Refunds/credits and non-finite values could update a subscription's paid date or price.
  Monthly updates now require a debit; annual matching checks finite amounts and UK dates.
- Instalment fields accepted NaN, infinity, negative values and malformed dates.
- Simultaneous preview submissions could launch duplicate jobs. Printing, preview starts
  and restore confirmation share the server's start lock, and active jobs block other starts.
- Invalid/zero/oversized PID markers could give misleading running status.
- Corrupt saved receipt structures could crash previews/archive pages.
- Several private JSON writers shared a temporary filename or created files with broad
  permissions. Shared atomic owner-only writes now cover tokens, receipt settings/captures,
  archived receipts, subscriptions, meal plans, local food state, routines, wealth history,
  finance caches and gig configuration.
- Backups accepted malformed settings/commitment/account/history shapes and JSON numeric
  overflow. Restore validates these before replacing files and reports rollback failures.
- Undated investment files could create a fictitious current valuation date.
- Invalid savings/investment numbers could contaminate totals.
- The public therapy-payee default contained a personal name. It is now blank; existing
  private saved settings are retained. Set the payee in Settings if it was never saved locally.
- Private authenticated responses now disable browser caching and include nosniff,
  same-origin referrer and frame headers. Map frames remain usable.
- Generated caches/logs/job markers/offline previews are excluded from Git.
- Removed identical duplicate definitions/imports and refreshed misleading README details.
- Added installation/development requirements and automatic repository checks for Python
  3.11 and 3.14. Local verification used Python 3.12; other versions are checked by CI.

## Verification and remaining limits

The final full suite passes 153 tests. Compilation and undefined-name checks pass.
Bandit reports no high-severity findings. Its remaining warnings concern validated,
fixed-host HTTPS requests, shell-free subprocess launches, non-security recipe randomness
and deliberate best-effort parsing. These were reviewed; a clean static scan does not
establish that every possible vulnerability is absent.

Live service credentials, provider responses and physical printer output require a local
smoke check. This was a code review and regression run, not an external penetration test.
The application still assumes one Waitress process for job coordination and login limits.
Atomic writes prevent partial JSON and temporary-file collisions; they do not make every
read/modify/write operation transactional across independent server processes. Multi-file
restore can still need recovery after a power/process failure. Logs/cache folders were
ignored prospectively; previously published files or credentials require separate cleanup.

The large legacy pipeline and duplicated business logic across older/newer finance modules
remain candidates for a staged refactor. A wholesale rewrite was avoided to preserve working
receipt behaviour. Archive pagination and a shared transactional store/job queue would be
useful as saved history or deployment scale grows.

After pulling, install `requirements.txt` in your project environment and restart the server.
