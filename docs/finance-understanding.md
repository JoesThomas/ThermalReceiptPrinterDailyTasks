# Understanding finance figures

Finance keeps its compact overview and existing section order. The new “Understand the figures” disclosure is collapsed by default; the home page is unchanged.

The disclosure explains cash, activity totals and runway, shows redacted per-source transaction request outcomes, and states the requested reporting window. Requests marked loaded may legitimately return no transactions. Requested dates are not proof that all payments have arrived. Transaction source labels are provider plus ordinal; no account IDs, token values or raw errors appear. Cash uses the GBP accounts selected on Choose cash accounts; until configured, it uses the first account returned by each HSBC and Monzo connection. Selected account names and their included balances are shown. Balance checks happen during the visit; they are not a claim of full multi-account balance coverage.

The lowest-balance line chart runs from today to the day before configured payday, or 30 days if no payday is set. It uses the same precise daily spending rate, dated payment events and protected buffer as runway. Future income is excluded. Missing data or unresolved repayments withhold the numeric forecast. The chart labels dates and amounts; payment details show what causes the decline.

ISA planning compares one monthly recorded-allowance target with non-negative cash remaining at the lowest point. It is a comparison, not a recurring affordability promise. ISA contributions are not automatically deducted from forecast events. Add a dated payment to include one. Incomplete ISA records remain estimates.

Savings explanations distinguish recorded balance change, net contributions and growth excluding flows. Unknown cash flows mean unknown growth. Recorded ISA interest is separately labelled with its tax-year period; it is not added a second time to monthly growth. Investment valuation gains are not described as interest.

Existing same-day repeat-payment checks remain reviewable and dismissible; explicit overlap between commitment matching terms is also flagged for review. Nothing is automatically cancelled, removed from totals or marked paid.

Opening Finance saves the latest observation for the current month in private `data/finance_monthly_snapshots.json`, retaining at most 60 months. It contains aggregate month-to-date income/spending, current cash, latest recorded savings/investment valuations, Amex debt and data coverage. No raw bank transactions or merchant names are saved in this file. Months without observations remain missing. These are snapshots at the displayed date, not reconstructed or verified month-end accounts; charts label their scope. Unknown balances are unavailable rather than zero. The file is gitignored, written atomically with private permissions, protected by a file lock, and included in validated private backups. Snapshot write failures do not block the current finance review.

Verification uses mock bank data and temporary private files; it does not contact banks or the printer.

Amazon shopping is excluded from the automatic daily variable-spending estimate used for runway and salary savings planning. Actual purchase totals and spending since salary still include it. Scheduled Amazon repayments remain commitments. A manual daily spending estimate overrides the automatic estimate. Future discretionary Amazon purchases are not budgeted by this exclusion.
