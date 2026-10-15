# Test finance: inputs and receipt detail

The test-finance form follows the order used to make a plan:

1. Income and forecast dates: scenario type, take-home income, first payday and duration.
2. Starting balances and everyday spending: optional bank/spending overrides, Amex balance and Monzo reserve target. Blank overrides use connected balances and the saved forecast; supplying both combined starting cash and daily spending makes a manual estimate.
3. Repayment and saving strategy: priority, split percentage, APR, savings amount or all-surplus option, and spare-bank-cash use after salary.
4. Savings accounts and goals: recorded account allocation, equal/custom shares and an overall target, with ISA assumptions in an optional disclosure.
5. Optional changes and comparisons: salary interruptions, one-off costs, spending differences and scheduled savings destinations/contribution comparisons.
6. Receipt and saved inputs: compact/detailed output and a named scenario.

Fields irrelevant to the chosen mode are hidden; manual starting savings is disabled when recorded accounts are selected. Invalid fields inside optional disclosures are revealed for correction. Input names, calculation rules and saved scenario identities are preserved.

The webpage generates a **compact receipt by default**, ordered as plan, transfers this payday, money to keep, balances at forecast end, goal progress and spending coverage. Scheduled savings are summarised rather than listed as individual upcoming payments. Internal Monzo transfers and protected cash top-ups remain distinct from new savings transfers. Shortfalls, unknown balances, capped standing orders and source warnings remain visible. This is a presentation change: it does not move money or change forecast allocations.

Choose **Detailed** for the original full calculation and assumptions. Receipt detail is saved with named scenario inputs. Existing programmatic `receipt(result, today)` calls retain detailed output for compatibility; the web generation route explicitly applies the form selection. Printing uses the archived generated receipt, so choose a different detail and regenerate before printing it.

The preview appears immediately below the form. Existing transfer workings and forecast comparisons remain below it on the webpage.
