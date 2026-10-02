# Premium Bonds prize history

Open **Premium Bonds winnings & return** from Finance Review or Savings.
Recognised incoming Premium Bonds bank transactions are saved privately whenever
live finance data is fetched, including during a live receipt preview. This saves
only prize dates, amounts, source labels and hashed transaction identities, not
raw bank descriptions, account numbers or the full transaction feed.

Enter your opening total amount held with its effective date, then a new total
balance on every deposit or withdrawal date. These balances are specific to this
return calculation and do not automatically change cash runway or general savings
balances. Enter historical prizes the bank can no longer retrieve. Editing a
balance for the same date updates it. Remove an incorrect manual prize then add
its replacement. Excluding a bank-imported prize retains a private tombstone so
refreshing the bank feed cannot reintroduce it.

The selected calendar year's recorded winnings include all known prizes through
today (or 31 December for a past year). The return calculation starts at 1 January
if an opening balance is known, otherwise at the first available balance date.
It sums recorded prizes in that same period and divides them by the daily weighted
average balance, multiplying by 100. Recorded prizes before that period are shown
in the yearly total but excluded from the return numerator. £10,000 in prizes over
a period with £10,000 average holdings is a 100% winnings return. Zero or unknown
average holdings produce no percentage. This is not guaranteed interest or an
annualised rate.

Balance entries carry forward until changed: missing balance changes affect the
percentage. Prize history is labelled unconfirmed until the user confirms all
prizes for the selected year through the displayed end date. Past completed years
with a full opening-balance period can then show an annual return. Current years
and shorter balance periods retain a recorded-period label. New/removed prizes
and edited balances clear the relevant completeness confirmation. Confirmations
do not advance themselves over unobserved days. A bank feed only retrieves a
limited window; missed checks can leave gaps that require manual backfill.

Stable bank transaction IDs are hashed to deduplicate refreshes. Without an ID,
a date/amount/description/reference fingerprint with occurrence count preserves
identical separate credits from the same fetched batch. Changed provider IDs or
descriptions can require manual review; perfect cross-feed identity is unavailable.
An unlinked manual prize matching date and amount is linked to a fetched prize
instead of counted twice. Check those matches if multiple identical prizes occur.

The ledger is `data/premium_bonds.json`, with a local process lock; both are ignored
by Git. It is included in the application's private backup/restore. The finance
receipt shows compact year-to-date winnings, recorded-period return and coverage
warnings once there is history. No personal balances or prize records are seeded
into the public code.
