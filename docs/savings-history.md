# Savings and investment balance history

Open **Savings & investments** from the control page or the finance review. The editor also works when bank data is unavailable. No code changes are needed to maintain an ISA or savings account.

Use a consistent account name and select Savings or Investment. Enter its valuation date and balance. Enter an earlier opening valuation if you have it. Saving the same name, type and date updates the existing entry. Older entries can be edited or removed in the expandable history.

Deposits and withdrawals cover the interval since the previous valuation for that account. Fill both fields, including zero for no activity, or leave both blank if unknown. Balance change and its percentage appear once two valuations are available. Growth excluding cash flows is shown only when every interval has recorded deposits and withdrawals. This is a cash-flow-adjusted pound change, not a time-weighted or annualised investment return. Backdating or removing a valuation invalidates cash flows on the following entry, because the interval changed; re-enter them when known.

Select a month to compare the last valuation on or before its beginning with the latest valuation recorded in it. If the beginning is missing, the first recorded valuation in that month is used and the actual dates are displayed. The current totals use the latest recorded balances even when reviewing an earlier month. Graphs show up to 24 dated observations per account, with exact figures in the expandable history. Different valuation dates mean the combined total is not necessarily a valuation at one instant.

Finance refreshes and finance receipts observe existing local savings and investment files. These are labelled local observations, not current provider data. Investment dates use the local file's `updated` date when present. Once an account has a manually entered valuation, it is maintained through the editor; refreshes will not overwrite it with an old file value. There is no Hargreaves Lansdown provider integration in this feature. Obtain the balance from the provider and enter it here.

The latest balances are used by the receipt's existing savings/investment totals. Newly added accounts are not automatically included in accessible runway savings or net cash; existing explicitly configured savings flags are preserved. Investment values remain separate from accessible cash. Dated comparison summaries also appear on finance receipts, with no claim of growth when flows are unknown.

Only account labels, valuations, dates, cash flows and source labels are saved in ignored `data/wealth_history.json`. No raw bank transaction history is added. Keep that local file in private backups; deleting it removes this feature's history. These records are not encrypted at rest and rely on the existing authenticated web interface and server filesystem access controls.
