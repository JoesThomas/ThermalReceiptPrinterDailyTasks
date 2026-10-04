# Receipt recovery and corrections

Use **Latest receipt** to open the newest saved receipt without regenerating it. A physical print saves the generated receipt before opening the printer connection, so it remains available if sending fails. Generated, sent and manually confirmed collected are separate states. A successful network send cannot prove that paper was collected.

Use **Correct information** to reach payment categories, commitments, deliveries, calendar locations, savings and cash accounts. Calendar location corrections are local overrides; edit event dates and times in the source calendar. Already categorised payments can be corrected from their transaction row.

Under Finance, **Choose cash accounts** selects HSBC and Monzo accounts included in cash and runway. Refresh Finance first to discover accounts, then select and refresh again. Until configured, the first account from each bank remains the default. Avoid counting the same savings both as selected cash and accessible savings. A missing selected account withholds the balance forecast until the selection is reviewed.

Payment dates show whether they are configured, observed from bank payments, estimated or unknown. Forecasts remain estimates and depend on source completeness.

Backup recovery checks restore the latest automatic backup into a temporary directory and compare its exported contents. They do not overwrite live data. Checks run daily while maintenance is running; the Backup page also provides a manual check and shows its result.

Account selections, discovery details, collection confirmations and calendar overrides stay in ignored private files. Private backups include selections, confirmations and overrides; bank credentials and transaction caches are excluded.
