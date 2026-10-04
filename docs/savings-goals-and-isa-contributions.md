# Private savings goals and ISA tax-year contributions

Savings and Finance show accessible progress bars for Premium Bonds holdings,
ordinary savings targets and combined recorded ISA contributions. Savings →
Goals & ISA contributions lets you set account types/targets and maintain dated
ISA entries without editing code. Add current valuations through the existing
Savings balance form or Premium Bonds holdings ledger. Existing valuations are
reused; the app does not assume a personal starting balance from the public repo.

Premium Bonds is measured against the £50,000 holding maximum. Multiple accounts
classified as your Premium Bonds are combined for that maximum. A dated Premium
Bonds holding takes precedence over an undated local observation, or over an older
manual valuation. It does not duplicate a holding already represented in Savings.
The progress bar is clamped to 100%, but any recorded excess remains visible.
Ordinary savings use a user-entered target and latest recorded balance.

ISA progress measures new-money contributions, not account value. The tax year
runs from 6 April through 5 April. Each account shows its recorded new money and
share of the combined adult ISA allowance, with one shared total across accounts.
Provider ISA transfers, investment growth, withdrawals and provider-confirmed
flexible replacements do not increase that new-money total. Withdrawals do not
automatically restore allowance. Confirm flexible replacement eligibility with
your provider before choosing that entry type. Existing interval deposit/withdrawal
fields on valuation history are not imported, because their exact payment dates
and ISA eligibility are unknown and could cross a tax-year boundary.

Enter all new contributions for the tax year, including other ISAs you own, then
confirm the coverage checkbox. Until then remaining allowance is labelled
unverified. Add/edit/remove actions invalidate coverage confirmation, so you can
review totals again. Dated entries can be edited or removed; historical totals
remain available and the selected year starts afresh on 6 April. Entry-time ISA
type is retained so an account classification change does not erase its recorded
past contributions. This ledger is manually maintained; the available 30-day bank
window cannot establish a complete tax-year history.

Defaults confirmed on 4 October 2026: the 2026/27 combined adult allowance is
£20,000. Known default overall limits cover 2024/25–2027/28; other years require a
configured limit. From April 2027 the cash ISA limit depends on age, so its default
is unknown until the user sets the applicable limit (£12,000 or £20,000 under the
published rules). No age is assumed or stored. Overall/cash limits are editable
per tax year. Lifetime, Help to Buy and Innovative Finance ISA product-specific limits are
not modelled. Classify these as Other adult ISA to count new contributions in the
shared total, and confirm subtype caps with the provider. Junior ISA contributions
use a separate child allowance and are not tracked by this adult ledger.
This is a record of inputs, not verification of regulatory eligibility.

The finance receipt gets a compact holdings/target and current ISA contributions
summary. Website-only progress bars do not widen the paper receipt. Account values,
targets and entries stay in the gitignored, owner-only `data/savings_goals.json`;
file locks serialize edits. The private backup includes and validates this ledger.
No personal balance or contribution history is seeded in the public source.

Sources:
- https://www.nsandi.com/products/premium-bonds
- https://www.gov.uk/individual-savings-accounts/how-isas-work
- https://www.gov.uk/individual-savings-accounts/transferring-your-isa
- https://www.gov.uk/individual-savings-accounts/withdrawing-your-money
- https://www.gov.uk/government/publications/fiscal-events-2026-factsheets/isa-reform-2027-anti-circumvention-rules-factsheet

Monthly ISA planning divides the recorded shared allowance remaining by the monthly payment dates remaining before 5 April. Set the first payment date to choose a monthly day; elapsed dates roll forward and short months use their last day without changing the original day. Payments include today if it is a scheduled date. Targets recalculate as contributions are recorded. Regular amounts round upwards to pennies; the final payment adjusts so the schedule totals exactly the remaining allowance. Incomplete contribution records produce an estimate. This is a shared adult ISA plan, not a separate allowance per account or permission to exceed cash/product-specific limits. Past years and unknown allowances have no monthly target. Planning preferences stay in the private, backed-up savings goals file.

Use Create an ISA on Goals & ISA to add a cash, stocks & shares, or other adult ISA with a dated current balance. The opening balance is a valuation, not a new contribution. Each account has a dated balance update form and editable payment/interest entries, grouped by selected tax year. Interest credited is displayed separately and excluded from the shared allowance and monthly target. Interest totals only cover recorded entries; investment valuation gains are not inferred as interest. Updating an entry does not automatically update the current balance: enter the provider's current valuation separately. These records use the existing private savings goals and wealth history files and backup support.

Cash ISA accounts also support an editable annual rate/AER with an effective date. This is the latest provider rate recorded for reference, not an interest forecast or a history of past rate changes. Changing it does not change recorded contributions, valuations or interest credits. ISA tax-year allowance limits remain separately editable.
