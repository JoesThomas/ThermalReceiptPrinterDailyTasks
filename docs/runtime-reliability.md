# Daily print outcomes, retry delays and release installations

## Daily outcomes

Home shows today's scheduled receipt separately from the most recent manual job,
with seven recent scheduled outcomes. The private operational history retains 90
days. Outcomes distinguish launching, running, sent to printer, saved preview,
failure, timeout and cancellation. Sending data does not confirm paper output.
An unreachable scheduled printer can still produce a saved preview; Home links to
the saved receipts for that day, rather than assuming the latest preview is still
the scheduled one. Away mode is recorded as a saved preview rather than a physical print.

A missing scheduled job is flagged after today's configured time. Existing date
markers remain valid and are labelled as older jobs without outcome details.
A dead or overdue worker is shown as interrupted. Reads do not rewrite history.

Daily launches use a cross-process lock. Only an explicit launch refusal can be
retried automatically. A job that launched, finished, failed or has an uncertain
launch outcome is not automatically printed again. History also prevents a
repeat if the date marker is lost after launch. Review the saved receipt before
requesting another print. Startup still does not catch up missed receipts.

## Integration retry delays

Cached receipt sources (weather/news/calendar/deliveries where using the shared
cache) delay automatic collection after two consecutive failures or partial
results. Delays start at one minute and increase to at most one hour. Existing
cache age limits and day/location identities remain unchanged: delay does not
make expired or yesterday's data valid. A complete collection resets the delay.

Periodic health probes keep their own failure counter. Repeated unsuccessful
probes wait for multiples of the configured interval, capped at 24 hours. Manual
**Check now** bypasses this delay, with a 30-second per-source minimum interval.
**Refresh sources** and targeted source retries bypass cache delay. Diagnostics
and API health show the next allowed retry time. No raw errors or private source
URLs are saved in retry metadata. Banking retrieval retains its existing worker
coalescing and retry cooldown; this change does not suppress bank token requests.

## Printer sensors

The explicit diagnostics check opens a bounded network connection and asks for
ESC/POS cover/error and paper-sensor status. It sends only `DLE EOT 2` and
`DLE EOT 4`, not feed, cut or print commands. Valid responses are decoded according
to the [Epson ESC/POS reference](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/dle_eot.html).
Responses must match its fixed status bits; ambiguous paper bits stay unknown.
An open cover makes paper status unknown because sensor bits can retain older
readings. Replies describe reported sensors, not proven physical output.

Support is model-dependent and has not been confirmed on the NetumScan printer.
Timeouts, malformed replies and unsupported USB sensor queries show **unknown**.
The explicit query is deferred during managed receipt jobs; managed print launches
are held off during the query. Do not run independent printer commands alongside
a diagnostic. Ordinary readiness checks continue to check connectivity only.

## Exact dependencies and separate upgrade checks

Install `requirements.lock` for runtime, or `requirements-dev.lock` for development.
These pin runtime and development dependencies resolved for the supported
Mac/Linux installations. Normal CI uses these versions on Python 3.11–3.14,
including browser/visual checks and a macOS installation smoke test.
`requirements.txt` and `requirements-dev.txt` remain the allowed upgrade ranges.

The separate **Dependency upgrade checks** workflow runs weekly or manually,
using those ranges through the same test workflow. It never changes or merges
release pins. To propose upgraded pins, use a clean virtual environment and run
`python tools/lock_dependencies.py --write`, then review both lock files and pass
CI before merging. Pins control versions, not platform binaries or system USB
libraries. Actual ARM/Pi acceptance remains a device check.
