# Amex payment protection

After updating and restarting, open **Finance review → Prevent Amex interest**.
Refresh bank data, check the statement and select **Enable Amex payment protection**.
It is disabled until you choose your payment arrangement: the app cannot infer
whether your Direct Debit pays the minimum, a fixed amount or the full statement.
These controls do not change your Amex settings or initiate payments.

## Statement and payments

Automatic mode uses `last_statement_balance`, `last_statement_date` and
`payment_due_date` from the existing TrueLayer card balance request. The separate
`payment_due` field is the **minimum**, not the amount required to clear the
statement. Missing statement fields never fall back to the current card balance.
Use manual mode when the bank does not supply them. The current balance can
include newer purchases that belong to a later statement.

Protection covers the first Amex card returned by the connection, matching credits
to that card's hashed identity. Only posted payment credits on Amex with explicit
payment descriptions qualify. Merchant refunds, reversals, payments on other
cards, proposed transfers and outgoing bank debits do not clear the reminder.
Ambiguous descriptions require manual confirmation rather than guessing.
Repayments on the statement date are excluded because their order relative to
statement creation is unknown. The manual confirmation total is compared with
bank-confirmed repayments using the larger total; it is never added twice. It
applies only to the recorded statement date. Enter a new statement each cycle
in manual mode, and check/reset manual confirmation when changing it.

## What prints

Daily information receipts show action warnings during the final seven days
(including seven, three and one day before the deadline), on the due date and
while payment remains unconfirmed afterwards. Other warnings cover insufficient
funds, an inadequate fixed/minimum Direct Debit, stale/incomplete evidence and
possible residual interest. A fully covered, funded planned full-statement Direct
Debit produces no daily warning. Finance receipts show statement balance, due
date, confirmed repayments, amount still unpaid, expected collection and reserves.
The web app also shows the warnings across its pages through the existing local
alert polling. An old saved receipt keeps the information it originally contained.

## Protected money

The unpaid statement replaces this cycle's Amex payment estimate in the main
forecast; it is not added on top of the existing £50 estimate. Future cycles keep
their configured payments because future statement balances are unknown. The
entire current statement reserve stays ahead of suggested savings, even when the
next payday comes before its deadline. Test finance also holds that money back
from spare-cash investment before the period containing its repayment. These
are planned cash allocations, not promises that a payment has been made.

Funding checks use the selected paying account and combined cash after the other
forecast bills, estimated everyday spending and protected reserves. They use the
latest bank check and local assumptions, not future income that has not arrived.
Unknown/stale statement or payment evidence withholds numeric allocation
recommendations. Checks use evidence from today or yesterday; refresh the bank
before relying on it. Forecasts are estimates, especially beyond the current bill.

A manual repayment near a full Direct Debit can leave both payments scheduled.
The app conservatively holds the original statement amount and asks you to
confirm the expected collection amount. Amex advises avoiding additional payments
in the four working days before collection; weekends and bank holidays matter.
This app does not cancel or adjust that collection. A carried balance or observed
interest produces a residual-interest caution, even after repayment.

Detection still runs on bank refreshes or finance receipt generation, not as
continuous bank monitoring. No interest guarantee is made: previous balances,
cash transactions, instalment arrangements and individual card terms can change
what is payable. Use the Amex statement as the authority.

## Local data

`data/amex_payment_protection.json` stores settings and a minimal, owner-only
snapshot: statement details, dated payment amounts, hashed card identities,
cash balances and forecast cost estimates. Raw payment descriptions, credentials
and card numbers are not retained here. The file is included in private backups.

Sources:

- [TrueLayer card balance fields](https://docs.truelayer.com/docs/account-and-card-data)
- [Amex interest guidance](https://www.americanexpress.com/en-gb/life-with-amex/credit-cards/credit-card-interest/)
- [Amex manual payments near Direct Debit collection](https://www.americanexpress.com/en-gb/customer-service/payments-and-billings/faq.manual-payment.html)
- [Amex residual interest](https://www.americanexpress.com/uk/customer-service/faq.how-is-interest-calculated.html)
