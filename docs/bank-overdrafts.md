# Bank cash and overdrafts

Cash forecasts exclude borrowing. For each selected HSBC/Monzo account, the collector subtracts the bank's reported `overdraft` from `available`, then uses the lower of that result and `current`. This retains pending outgoing holds and negative balances while avoiding counting an unused overdraft as savings money. When `available` is absent, `current` is used directly without deducting an allowance again. Amex credit-card handling is unchanged.

If the bank omits its overdraft limit, the lower of current and available is used. This excludes extra credit above the current balance but cannot identify pending outgoing holds offset by an unknown allowance. Set the included allowance manually for that account in **Finance → Choose cash accounts → Overdraft allowances** (`/finance/accounts`). Blank uses bank data; 0 explicitly says the available balance includes no borrowing. An override replaces the reported allowance, rather than adding to it.

Overrides are stored privately in `data/bank_overdrafts.json`, indexed by provider and account ID, and included in private backups. They apply only to the matching account. Review after reconnecting if account IDs change. Saving an override invalidates the cached finance snapshot; refresh Finance and generate a fresh test receipt to apply it. Previously generated receipts keep their original figures.

Both test receipt layouts show the corrected account balance, the bank's reported available amount and the allowance when a deduction applies. Individual, provider and combined totals use corrected cash. Manually entered starting cash is already an owned-cash assumption and is not adjusted again.

TrueLayer documents that available balances include pending transactions and overdraft, while current balances exclude pending transactions: https://support.truelayer.com/hc/en-us/articles/360004571178-What-is-the-difference-between-the-balances-returned
