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
