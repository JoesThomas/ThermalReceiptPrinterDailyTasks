# Test finance: Amex before reserve top-ups

In the **Amex first** strategy, allocation now follows:

1. Listed bills, scheduled repayments and everyday spending, including food and necessities.
2. Extra Amex repayment, using available bank cash after those costs.
3. The configured HSBC bank target, Monzo bank target, and physical cash top-up.
4. Optional confirmed instalment settlements, then extra savings/investments.

Tax and other earmarked obligations stay protected. The HSBC/Cash/Monzo amounts
are targets, not an untouchable deduction before Amex. A bank target below £1,000
may therefore be deliberately unfilled while Amex is owed. This is shown as an
unfilled target, separately from a shortfall in essentials or other protected money.
Other allocation strategies retain their existing reserve-first policy.

Within the target group, bank money first covers the HSBC target, then Monzo.
Physical cash is withdrawn only from money above those bank targets, after the
card is covered. Partial cash top-ups are supported; each funded transfer credits
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
