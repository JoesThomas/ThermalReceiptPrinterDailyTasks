# Finance suggestions and cash runway

Finance review now explains upcoming payments, unmatched commitments, approaching
renewals, contracts ending soon, possible recurring charges and unusual repeats.
Each suggestion includes its evidence. Dismissals are saved locally for 30 days;
a change in evidence can produce a fresh suggestion. No bank transactions are
saved by this feature.

The receipt and web page use the same cash projection. Starting with live
current-account cash, it protects the configured buffer, reserves known payment
amounts on their dates, and estimates everyday spending from the available
30-day window. Actual bill matches are removed from this spending estimate so
they are not counted twice. Existing debt balances are not subtracted in full;
their scheduled repayments are included instead.

## Improve the inputs

- Set each monthly commitment's usual payment day on the home page.
- Keep instalment schedules, remaining balances and end dates up to date.
- Give annual subscriptions a renewal date and amount.
- In Finance review, enter payday, the protected cash buffer and optionally an
  everyday spending estimate. Leaving that estimate blank uses bank records.
- Add dated cash payments for card repayments or one-off expenses. Use the same
  name as a monthly commitment to set its date without counting it twice.

Future income is excluded from runway: this answers how long existing funds
could cover the listed payments and estimated spending without more income.
A separate allowance shows cash left after listed payments before payday.
Unknown payment dates are reserved conservatively and flagged. Missing balances,
incomplete transaction data or an unscheduled card repayment prevent a numeric
runway from being presented as verified. The projection covers up to 365 days;
“over 365 days” is a horizon limit rather than a precise exhaustion date.

The output remains an estimate. Bank records can arrive late, spending can change,
and unlisted payments cannot be predicted. Verify the included payments and update
local figures before making decisions based on it. Savings are included only when
explicitly marked as accessible for runway in the private savings file.

Projection inputs stay in `data/finance_settings.json`, monthly and annual entries
in `data/subscriptions.json`, and dismissal IDs in `data/finance_suggestions.json`.
These private files are ignored by Git. The public repository contains code and
generic examples only.

## Estimated monthly payment dates

A past bank payment or recorded `last_paid` date estimates the next monthly
payment day. If that estimated day has already passed, the forecast rolls to the
next occurrence rather than inventing unpaid arrears reserved today. This avoids
counting an inferred rent or Sky payment twice in one pay period. Explicit
configured overdue dates and unknown payment dates retain their conservative
reserves; real overdue amounts can be recorded as dated commitments.
