# Changes and release history

Group related implementation, documentation and regression coverage into one pull
request per coherent update. Small follow-up fixes belong on that branch. Merge
with **Squash and merge**, using a descriptive title, so `main` gains one commit
for the completed update rather than every intermediate fix. A push uploads
commits; the commit history is what squash merging keeps concise.

Run the required checks before merging:

```sh
python -m compileall -q .
python -m ruff check . --select F821,F822,F823,F811
python tools/format_templates.py --check
python -m unittest discover -s tests -v
python -m bandit -r . --exclude ./tests -lll
```

GitHub Actions also checks Python 3.11–3.14 and the browser flows/responsive layouts.
Use `python tools/benchmark_hot_paths.py` to compare local computation on synthetic
inputs without credentials, API calls or a printer. Do not use timing assertions
in the unit suite; test concurrency, bounded work and result consistency instead.

Consolidate equivalent behaviour into shared helpers. Keep compatibility exports
and separate rules when similarly named functions intentionally have different
semantics. Preserve dated financial observations, account identities, provider
coverage, exact money calculations and source timeout/fallback behaviour.

Changing already-published commit history is a separate operation from improving
code. Prepare a review branch and a backup of the old `main`, verify identical
final trees, and agree the replacement before force-updating the branch. Existing
checkouts then need to be realigned or cloned again. Keep the backup available;
rewriting `main` does not erase pull-request records or historical activity.
