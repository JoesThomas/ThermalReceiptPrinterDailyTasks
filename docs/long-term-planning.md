# Long-term planning

Open **Finance → Test finance → Long-term planning**, or **More tools → Long-term
planning**. The new page is a separate, editable monthly scenario model for
1–40 years. The existing payday test remains the source for dated near-term
payment instructions; its old dates beyond five years are still labelled pace
extrapolations. The long-term page calculates income, costs, debt and each account
through every modelled month instead of extrapolating one year's contributions.
Nothing changes live balances, sends transfers or prints automatically.

## Start a plan

1. Enter take-home salary, other cash income **after tax**, fixed bills, everyday
   spending and the minimum bank cash to retain. Enter combined cash excluding
   unused overdrafts, or split it into named bank accounts without duplicating it.
2. Copy locally recorded savings into the form if useful, then review their dates,
   balances and types. This reads local records only; no bank data is fetched.
   Add debts, pensions and property manually. Property values should reflect the
   user's ownership; record mortgage liabilities as separate debt accounts.
3. Configure contributions, limits and optional lower/expected/higher returns for
   each account. Zero is the default growth/prize assumption. Bank reserve targets
   are held cash; a savings goal is a milestone unless its contribution-stop switch
   is enabled. An explicit limit still applies, and Premium Bonds stop at £50,000.
4. Add life changes and goals, calculate, and compare assumption cases. Results
   appear above the collapsed editing form. Inspect a selected year for its full
   monthly account equations. Save a named baseline to preserve those assumptions.
5. Record actual dated balances against saved accounts. Exact month-end dates can
   be compared with that baseline. Rebase copies latest observed balances into a
   new form starting today; it does not overwrite the old baseline or live records.

## Cash priorities and uncertainty

Bills, necessities, scheduled debt payments and explicitly scheduled savings are
commitments. Extra Amex payments precede confirmed eligible whole-debt settlements,
then bank/cash reserve targets, then discretionary savings and investment.
Ineligible debts keep their normal payments. Whole settlements are considered only
when affordable in that month. The monthly model does not provide settlement
quotes or change collection arrangements. Everyday spending uses the configured
maximum while Amex is owed or bank cash is overdrawn, then its normal amount.
Bank deficits remain visible, count as debt in net worth, and trigger a minimum
warning. They do not create free money or assume an available overdraft facility.

The first bank receives salary and other income. Other bank targets are funded by
explicit internal ledger transfers. Income-funded commitments can continue without
salary; extra investing is disabled without salary unless explicitly enabled.
Pensions do not automatically share extra surplus: opt in or set their monthly
contribution. Their entered access date controls withdrawals; eligibility is not
inferred. Property and locked pensions remain separate from accessible assets.
Accessible investments are not equivalent to bank cash.

Savings/cash ISA rates model interest; investment/property/pension rates model
illustrative total returns, including any entered dividend yield. Cash yield
splits that total return rather than adding another return. Losses are allowed.
Premium Bonds use an entered **average prize assumption**, not interest or a
prediction of individual draws. Existing holdings are assumed eligible. New
purchases wait a full calendar month; reinvested prizes enter the following draw.
Reinvestment respects the £50,000 cap; excess is held as separate assumed payout
cash. A chosen other savings destination respects its limits and shared ISA room.

Assumed payouts into the bank are displayed separately, not used implicitly to
pay bills or make discretionary transfers. A dated **Realise payout** event can
explicitly bring that modelled payout cash into the cash-flow plan. Withdrawals
from accounts are also explicit. These remain assumptions, not confirmation that
money has actually been received. Lower/expected/higher cases are not statistical
confidence intervals. Negative investment outcomes are possible.

## Life changes, replacement costs and goals

Salary, other income, bills and spending events replace the ongoing monthly
amount. Contribution events replace an account's contribution. Income/cost events
add one-off cash flows, with optional month intervals for replacements such as a
vehicle or appliances. Future costs increase with the chosen inflation assumption.
Asset purchase events exchange cash for property/illiquid asset value; they cannot
bypass financial-account contribution limits. Withdrawals respect actual event
access dates and the configured flat tax assumption. Past changes are applied
when rebasing; past one-off cash flows are not replayed. Recurrences are advanced
to their next future occurrence.

Goals can use a fixed future amount or an inflation-adjusted target. They compare
with the last monthly model point **on or before** the requested date; a deadline
before the first month-end uses the entered opening balance. Later-month income
is never borrowed to make an earlier goal look funded. Debt goals mean owing no
more than the entered target, rather than accumulating an asset balance.
The additional monthly saving/repayment figure is an annuity estimate under a
constant net rate after entered flat tax/fee assumptions, not an optimised or
promised return. Premium Bond prizes are not assumed in this reverse calculation.
Limits, monthly surplus and other goals may require a different allocation. A
first estimated crossing is not a guarantee the goal stays funded after later
withdrawals or losses. The chosen-date balance and shortfall are shown separately.

Compare a permanently missed first salary and a first salary delayed by one month.
The delayed case catches up only the amount originally deferred, including a
partial first month. The page also quantifies the effect of £100 less initial
monthly spending or £100 more initial monthly take-home income, subject to the
same later growth assumptions.

## Assumptions and boundaries

* Inflation starts at an illustrative **2%** and is editable. The page shows both
  future pounds and purchasing power in today's money, plus milestone years.
* The monthly model prorates first/last partial months and ends one day before the
  chosen anniversary. Events occur in the named calendar month; it is not a daily
  cash-flow or payment-timing forecast. Growth uses remaining opening capital;
  new allocations are treated as month-end deposits. Fees use the pre-return
  monthly balance. Provider credit dates, prices and interest/prize rates are not
  fetched or predicted.
* Fee and tax assumptions default to zero. Income is entered net; optional account
  tax is a flat estimate, not a UK income-tax, CGT or pension-withdrawal calculation.
  ISA growth and Premium Bond prizes are not taxed in the model. Pension/property
  values remain gross until a modelled withdrawal or sale. No pension tax relief,
  Lifetime ISA bonus, debt settlement fee or automatic bank-overdraft interest is
  inferred.
* Shared annual ISA subscription room and a cash ISA sub-limit are editable future
  assumptions, with an April tax-year reset for month-end allocations. The initial
  £20,000 shared assumption reflects 2026/27, not a promise of future rules. Enter
  used subscriptions per account. This does not replace the main ISA ledger or
  support all specialist ISA rules. Check future cash restrictions separately.
* Sources: [ISA overview](https://www.gov.uk/individual-savings-accounts/overview),
  [Premium Bonds](https://www.nsandi.com/products/premium-bonds),
  [prize reinvestment](https://www.nsandi.com/files/asset/pdf/premium-bonds-prize-options.pdf),
  [investment uncertainty](https://www.moneyhelper.org.uk/en/savings/investing/thinking-about-investing-make-sure-you-understand-the-risks).

## Receipts, privacy and performance

Create a concise archived summary, review it, then use the explicit print button.
It shows outcome cases, goals and resilience, not decades of monthly rows. Daily
receipts are unaffected. The payday test additionally gains a savings overview,
shorter compact goals, clear later-settlement labels, an editable post-Amex
spending budget and an optional monthly-paper breakdown. Monthly bank balances
under Amex first follow funded Monzo transfers rather than reallocating bill money
into a fictional Monzo target; upcoming costs, held bank reserves and unallocated
cash are shown separately.

Private baselines and observations use `data/long_term_plans.json`, with atomic,
owner-only writes and the existing authenticated/CSRF-protected interface. The file
is ignored by Git and included in validated private backups. Saved baselines are
immutable versions; observations can be removed independently. Storage is bounded
at 12 baselines, 1,000 observations and 250 KB. Calculations are bounded at 40
accounts, 100 events, 50 goals and 40 years. Full account workings are shown one
year at a time; other scenarios retain compact ledgers to limit memory use.
