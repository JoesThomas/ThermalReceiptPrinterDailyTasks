# Expected non-salary income

The main Finance page (`/finance-review#expected-income`) lets you add, edit, pause and delete expected non-salary payments such as rent. Each has a name, positive GBP amount, first date, optional inclusive last date, and one-off, monthly, month-end or yearly frequency. No future salary is inferred or added.

The original Cash runway remains a no-future-income baseline. A separate comparison adds only enabled expected payments on their scheduled dates, using the same starting cash, bills, everyday spending and protected buffer, over the next 30 days. It excludes accessible savings. A later receipt cannot erase an earlier shortfall. The end-balance card and receipt figure appear only when no protected-buffer shortfall occurs during this 30-day period. If cash runs short, the first shortfall date is shown instead of a misleading balance after funds run out. This outlook is independent of Test finance dates and the main baseline runway's five-year search horizon. Figures are withheld when the baseline lacks complete, fresh data. The main finance receipt includes a compact comparison and up to six upcoming payment rows.

Only dates strictly after today in Europe/London are added. Today's bank balance may already include today's incoming payment, so adding it again would double count. Past occurrences are never carried forward. Expectations are not confirmed bank transactions and never change observed income, salary allocation, balance history or test-finance inputs. Update an expectation when cancelled or paid early, since no automatic transaction matching is assumed.

Monthly payments preserve the original calendar day, clamping to the last valid day in shorter months. Month-end always uses the month's final day; yearly leap-day payments use 28 February in non-leap years. End dates are inclusive.

Data lives privately in `data/expected_income.json`, with locked, atomic updates, validation and private backup support. Invalid storage is reported without replacing the file. Editing expectations recalculates from the existing bank snapshot without requiring another bank request. Saved/printed receipts retain their original figures.
