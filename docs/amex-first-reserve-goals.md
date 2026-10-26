# Test finance: Amex before reserve top-ups

In the **Amex first** strategy, allocation now follows:

1. Listed bills, scheduled repayments and everyday spending, including food and necessities.
2. Extra Amex repayment, using available bank cash after those costs.
3. Optional confirmed fee-free instalment settlements.
4. The configured HSBC bank target, Monzo bank target, and physical cash top-up.
5. Extra savings/investments.

Tax and other earmarked obligations stay protected. The HSBC/Cash/Monzo amounts
are targets, not an untouchable deduction before Amex. A bank target below £1,000
may therefore be deliberately unfilled while Amex is owed. This is shown as an
unfilled target, separately from a shortfall in essentials or other protected money.
Other allocation strategies retain their existing reserve-first policy.

Within the target group, bank money first covers the HSBC target, then Monzo.
Physical cash is withdrawn only from money above those bank targets, after the
card and eligible early repayments are covered. Partial cash top-ups are supported; each funded transfer credits
its savings goal on that date, once. Monzo transfers only redistribute bank money.
The end-of-forecast bank split uses the same HSBC-first rule.

Existing scheduled savings, such as the £25 Hargreaves Lansdown standing order,
continue as listed commitments. The new priority controls extra allocations; it
never cancels an actual standing order or direct debit. If the card balance is
unknown, confirm it before discretionary moves are suggested. APR assumptions and
provider collection schedules still apply.

## £700 monthly maximum while owed or overdrawn

The test form defaults to **Limit everyday spending while Amex is owed or an
account is below £0**, with a configurable **£700/month** ceiling. This applies
when Amex is owed at the start of a pay period, an HSBC/Monzo/recorded cash balance
is negative, or the normal spending estimate would overdraw spendable cash in
that period. Individual connected bank accounts are checked, even when their
combined total is positive. Later periods use projected cash rather than keeping
an old overdraft flag forever.

The forecast keeps the lower of the normal daily spending estimate and the
monthly ceiling divided across that pay period. It does not add £700 on top of
existing spending or raise a lower budget. The whole period keeps its selected
budget even if Amex clears part-way through it. Later debt-free, non-overdrawn
periods return to the normal estimate. Positive but unfilled savings targets do
not by themselves trigger the ceiling. The spending amount is still kept before
Amex repayment, so food and necessities are not taken out of the repayment money.

The option and maximum are saved with named scenarios and generated receipts.
Older saved inputs keep their recorded assumptions until reviewed and saved again.

Amex repayment can use available cash without salary. Extra investment of spare
bank cash retains its salary requirement and waits for funded reserve targets.
The simulation never sends money or changes live account balances.

## Goal dates beyond the forecast

Accounts not reaching their target within the selected forecast first use the
existing cash-flow extension (up to five years). If no funded date is found there,
a separate **Long-term estimate** continues the final simulated year's monthly
contribution pace and recorded savings AER, for up to 100 additional years.
Scheduled savings are included; investment market returns are not assumed.
This is an extrapolation, not an extension of funded cash-flow checks: it does not
model future changes to income, bills, rates, tax allowances or redistribution
when other goals finish. The receipt and webpage label that distinction.
No estimate is offered for a failing pathway, an explicit salary end date,
a one-off lump sum, an incompatible account limit, or a non-growing balance.

## Editable minimum bank balance

Test finance defaults **Minimum bank balance to keep** to £500. It protects that
much combined bank cash before extra Amex repayments, selected early repayments,
physical cash top-ups or extra savings. The floor is included within the bank
reserve targets, not added to them. Tax and other earmarks remain additional.
£0 disables this floor. Other strategies retain any stronger existing reserve.
Bills, food and necessities remain commitments: if income cannot cover them and
the minimum, the forecast shows the actual lower balance and a funding warning,
not an invented £500. **Lowest projected bank balance** remains a calculated
result; the configured minimum is printed next to it.

The setting persists with generated and named scenarios. Older archived inputs
without this field keep their historical assumptions in comparisons; opening the
current form defaults the new field to £500 until reviewed and regenerated.

## Calendar month-end balances

Both receipt detail modes show **Balances at [month/year] end** for each calendar
month-end within the selected forecast, alongside final forecast balances. These
are end-of-day snapshots after actual forecast income, payments, extra debt
payments, savings transfers, physical cash top-ups and estimated savings interest.
Bank splits follow the existing HSBC/Monzo target allocation rule; savings are
excluded from bank cash and Amex is shown as debt owed. Unavailable balances stay
unavailable. Unassigned savings are shown separately if saved accounts are off.
The webpage and named comparisons provide the same snapshots in an expandable
list. Beyond any funding breach, the snapshots are explicitly hypothetical.

### Individual savings interest

Each month-end account balance now shows **Interest this month** for savings
accounts and cash ISAs with a recorded AER. This is the modelled calendar month's
interest (or the partial month covered), already included in the balance, before
tax and fees. The website also shows cumulative interest since the calculation
start. Forecast-end account balances show **Interest over forecast** for each
eligible account; the existing total remains the sum of individual estimates.

Monthly values are differences of cumulative interest rounded to pennies, so the
breakdown reconciles without adding interest twice. Contributions earn interest
only after their transfer date. A later first payday does not move earlier
calendar interest into that payday's month. Recorded zero rates show £0.00;
missing balances show unavailable. Physical cash reserves, investment market
returns and Premium Bonds prizes are not modelled as savings interest. Rates stay
constant at the recorded AER; provider credit dates and future rate changes are
not predicted. This disclosure does not change transfer allocations or balances.
