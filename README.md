# Thermal Receipt Printer — Complete Modular

This is the complete merged project based on `thermal_receipt_modular_v3`, with
the later calendar/travel, news, finance, savings and savings-growth work folded
back into the project.

## Physical receipts

1. Daily Information — weather + 3 UK news summaries + 3 Birmingham/local summaries
2. Daily Actions — calendar, travel/leave-by, to-do, deliveries, other requested checks
3. Food — daily recipe; Saturday plan/shopping; Sunday prep
4. Finance — only when requested

## Added since modular v3

- Calendar addresses preserved from iCal
- Driving, public transport and short walking options
- Leave-by times and previous-event journey chaining
- Three UK + three Birmingham/local news items with compact source-derived RSS summaries
- Optional news disappears if unavailable
- Finance uses £ formatting
- Upcoming payments are one line: name / amount / date
- Last-30-day spending versus usual 30-day spending
- Category trends using the preceding 90-day baseline
- Transfers/savings/income/card repayments excluded from spending categories
- Savings loaded from `data/savings.json`
- Per-savings-account `include_in_net_cash` and `include_in_runway`
- Runway bar removed
- Available-cash + accessible-savings runway
- Quarterly/yearly finance snapshots in `data/finance_history.json`
- Quarterly/yearly savings growth comparisons
- Meal planner compatibility fixed so the live legacy collector can use modular `data/`

## Setup

Copy `passwords.example.json` to `passwords.json` and fill in your private
credentials/URLs. Keep `passwords.json` out of source control.

For travel estimates, fill in:

- `google_maps.routes_api_key`
- `locations.home`

Edit:

- `data/savings.json` for savings balances and runway flags
- `data/finance_categories.json` for merchant category overrides
- meal JSON files under `data/` for recipes/preferences/inventory

## Commands

Validate JSON:
`python main.py --validate`

Run health checks:
`python main.py --health`

Preview modular renderer:
`python main.py --preview`

Run live printer:
`python main.py`

The live external collectors remain in `legacy_main.py`; the newer modules are
separated so they can continue to be migrated out cleanly.

## Debt and payday receipt

The finance receipt shows live HSBC and Monzo cash, live Amex debt, and any
instalment balances in `data/subscriptions.json`. It separates short-term debt
from a future mortgage. The `NET LIQUID` figure subtracts short-term debt from
cash. Existing savings, investments, spending, runway and period reviews still
print below the new cash/debt/payday summary.

Copy `data/finance_settings.example.json` to `data/finance_settings.json` and
replace the example values with your own. This private file is ignored by Git.
Add other debts (including a mortgage), a future `next_payday`, a protected
buffer, and individual dated `commitments`. Do not duplicate Amex or an existing
instalment name: live Amex and known instalment balances take precedence. Enter
payments due before payday, not the entire card or loan balance. The daily
allowance is cash minus listed commitments and the buffer, divided by days left.
Without a future payday the receipt says the forecast is unconfigured.

`forecast_events` are separate signed cash changes over the next 30 days. Only
listed events contribute to that projection; it does not estimate discretionary
spending. If a bill is in `commitments` and `forecast_events`, the two sections
answer separate questions and are not summed together. Refresh dated entries
after payments and payday. Optional `savings_goals` display saved and target
amounts.

### Rolling dates and review date

Set `payday_repeat` to `monthly` to calculate the next payday from the original
`next_payday` date without editing the file each month. Add `repeat: "monthly"`
or `repeat: "yearly"` to a dated commitment; omit it for a one-time payment.
Add the same `repeat` field to a `forecast_events` row to roll that dated
cash movement in the 30-day forecast. An occurrence on payday is excluded from
the before-payday budget. Dates on
29–31 use the last day of shorter months and return to their original day in
later months. Rolling happens when printing and does not rewrite your settings.
If payday moves for a weekend or bank holiday, update the anchor date manually.

Set `reviewed_on` to the date you last checked the *manual* payment amounts and
schedule. The receipt shows that date beside the payday calculation and warns
if it is missing, in the future or more than 30 days old. The date does not
claim that bank balances were refreshed. Rolling a recurring payment assumes it
still applies at the configured amount; update or remove it when that changes.

### Finance source labels

The finance receipt marks figures with a compact legend: `[B]` is a bank balance
from TrueLayer, `[F]` is a stored value from a local finance, savings,
instalment or investment file, `[C]` is calculated from those inputs, and `[E]`
is a forward estimate. The 30-day spending section uses bank transactions and
calculated totals; payday and future cash figures depend on dated file entries.
A bank label identifies its source, not its age or a guarantee that the bank
updated that figure today. The `reviewed_on` date covers manual payment settings
only. Monthly commitment labels indicate whether a stored bill was matched to
bank activity; an unmatched item may still need checking.
