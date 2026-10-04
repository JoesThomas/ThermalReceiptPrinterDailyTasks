# Private planning and display options

Finance has an expandable planning area. **Private plans** also opens a page that can edit purchases and savings priorities without bank access. Refresh Finance to calculate them from current bank data.

Purchases have a name, GBP cost, date and an enabled flag. They are hypothetical: the comparison subtracts them from the same cash forecast and protects the existing reserve, while the main runway and actual spending stay unchanged. Purchases before today are ignored; purchases beyond the forecast horizon are identified. Disable or remove a purchase when it has become an actual transaction to avoid counting it again in the scenario.

Savings priorities have a destination, monthly contribution target and priority number (lower first; equal priorities sort by name). Their combined target is used for the salary plan when no manual salary savings target is configured. A manual target takes precedence. Only the affordable contribution is divided. Planned purchases before payday use additional spending money first, then reduce the hypothetical savings budget. ISA and Premium Bonds allocations respect recorded remaining allowance/holding space; missing space withholds that destination. These are recommendations, not automatic transfers. Existing emergency bank and physical cash reserves remain protected separately.

Renewal reminders show recorded annual renewals and contract endings within 60 days. They are not automatic cancellations and do not infer providers' cancellation notice periods.

An ended month's latest aggregate observation can be marked reviewed after explicit confirmation. Its figures, observation date and coverage are frozen privately; incomplete history remains labelled incomplete. Reconfirming deliberately replaces the reviewed snapshot. No missing transactions are reconstructed, and the review is not a bank reconciliation guarantee.

On Receipt, **Choose receipt sections** generates or prints selected sections together in the configured order. Finance is explicitly requested when selected. Standard job locks, cancellation, progress and timeouts still apply. The CLI equivalent is `python main.py --live-preview --pages actions finance`; omit `--live-preview` to print. `--only` and `--pages` cannot be combined.

**Display & accessibility** offers normal/large/larger web text, stronger contrast and reduced animation. Preferences are stored in the current browser; printed receipt sizing is unchanged. Operating-system reduced-motion preferences are respected. These settings supplement semantic labels and focus controls; they do not constitute a formal accessibility audit.

Planning is stored in ignored `data/finance_planning.json` with owner-only permissions and included in private backups. No personal values are seeded in the public repository.
