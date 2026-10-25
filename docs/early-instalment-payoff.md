# Test finance: early instalment settlement

In **Finance → Test finance → Pay instalments off early**, enable the option and
select the payment plans you have confirmed allow fee-free settlement. It is off
by default. Eligible choices need a known positive outstanding balance, a positive
monthly payment, and a uniquely identifiable dated schedule. Ordinary bills,
mortgages and credit cards are excluded. Amex keeps its existing repayment model.

The forecast uses the same surplus allocation as the existing strategy: recurring
income after bills, spending and reserves, plus spare bank cash only when its
existing option is enabled and salary is actually paid. Without salary that spare
cash rule remains paused; other recurring income can still fund settlements.
The existing lump-only allocation behaviour is unchanged.

Amex first allocates extra money to Amex before instalment settlement. Split
allocates its chosen Amex share first. Selected instalment settlements take
priority over extra savings, including under Savings first. Remaining money
follows the existing savings settings, account limits and ISA rules.

Each period tries the smallest affordable whole outstanding balance first.
Unaffordable plans retain scheduled payments and are reconsidered next period.
Payments made earlier in the simulation reduce the remaining balance. The full
settlement includes that period's reserved instalments: they are removed from
bills, and only the difference consumes additional surplus. Later payments on
that plan are removed too. No partial extra instalment repayments are assumed.
If the resulting pathway breaches reserves anywhere in the selected horizon,
early settlements are withheld and the original pathway is recalculated. That
pathway may still have a funding warning; this does not make an unfunded plan safe.
Goal-date extensions apply the same checks within their longer horizon.

The webpage lists settlement dates, amounts and projected remaining balances.
Both receipt detail modes show settlements, and the first-period transfer list
includes the full amount to send. The detailed receipt distinguishes replaced
scheduled payments from the extra allocation. The simulation never sends money,
marks live debts as paid or changes real direct debits/collection instructions.

Only the recorded balance is used, not a lender settlement quote or a calculation
of interest/fee savings. Confirm the actual settlement amount and treatment of
pending collections with the provider. A changed balance or schedule invalidates
that plan's previous selection so it must be reviewed and selected again. Named
scenarios preserve the option and selected confirmations; older scenarios remain
valid and leave early payoff off.
