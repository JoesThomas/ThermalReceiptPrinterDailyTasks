# Amex interest alerts

Amex transaction retrieval checks for posted interest charges using TrueLayer's
`INTEREST` category and explicit interest-charge descriptions. Only transactions
from the Amex card source qualify. Credits, refunds, reversals and ordinary fees
are excluded. This detects actual posted charges, not forecast interest or APR.

Warnings show the charge date, currency and amount throughout the web application.
Open pages check the small local warning file every ten seconds without triggering
bank requests, refreshing the page or losing unsaved input. The warning appears
on daily information receipts when finance is not due, and on finance receipts
when that section prints. Acknowledging displayed charges removes their warnings;
a later charge creates a new warning. Acknowledgement does not pay or reverse a
charge. Subsequent refunds do not automatically acknowledge an earlier charge.

Detection happens when the app retrieves Amex transactions (finance review refresh
or a finance receipt). It is **not continuous bank monitoring**: the app cannot
report an unposted charge or one the provider has not yet returned. Use Refresh
bank data on the finance review to request a check. A failed or incomplete bank
check does not remove previously detected warnings. An unavailable Amex source
must not be interpreted as confirmation that no interest was charged.

Only charge dates, amounts, currencies, acknowledgement flags and hashed identities
are saved in the owner-only `data/amex_interest_alerts.json` file. Raw descriptions
and card identifiers are not retained in that ledger. It is included in private
backups. Stable provider identifiers are preferred over request-specific IDs;
when unavailable, a fingerprint of the transaction fields is used.

Reference: [TrueLayer card transactions](https://docs.truelayer.com/reference/getcardtransactions)
and [account and card data](https://docs.truelayer.com/docs/account-and-card-data).
