# Daily attention, scenario comparisons and the refill test

Home's **Needs attention** panel combines saved reports of failed/missed daily
prints, settings recovery, printer issues, bank refresh problems and integration
retry delays. Each item links to the relevant review screen. It reads small local
status files; it does not fetch bank transactions, contact providers or probe the
printer just because Home is opened. A clear panel means no issue was reported by
the saved checks, not that every service has been checked live.

Save at least two named plans on **Finance → Test finance**, then use **Compare
saved plans**. Both forecasts share one bank collection and one set of local
settings, commitments and savings accounts. Their own cash, spending and Amex
balance overrides are applied separately. If both plans specify starting cash
and daily spending, no bank lookup is needed. Comparisons show first-period
transfers, debt clearance, savings goal dates, lowest bank balance and differing
inputs. They do not print, move money, update live balances or replace the last
printable test receipt. Old dates must be reviewed in the saved plan before
comparison; differing forecast horizons are shown explicitly.

**Test after refilling paper** is on Home and **Printer & source diagnostics**.
It prints only `PAPER FEED TEST` and the small ASCII thumbs-up supplied for this
project, then cuts the paper. It skips the initial separation cut to reduce blank
paper while retaining the printer's normal final feed/cut. It does not generate a
full receipt, retrieve weather or access banks. The supervised worker still
handles failures and cancellation. Intentional repeats are allowed after the
previous test finishes. Check the physical drawing before requesting a full
receipt; software cannot infer paper delivery from a successful write.
