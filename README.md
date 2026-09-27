# Thermal Receipt Printer — Complete Modular

This is the complete merged project based on `thermal_receipt_modular_v3`, with
the later calendar/travel, news, finance, savings and savings-growth work folded
back into the project.

## Physical receipts

1. Daily Information — weather + 3 UK news summaries + up to 3 BBC Birmingham & Black Country stories + up to 3 BBC Sport stories
2. Daily Actions — calendar, travel/leave-by, to-do, deliveries, other requested checks
3. Food — daily recipe; Saturday plan/shopping; Sunday prep
4. Finance — only when requested

## Added since modular v3

- Calendar addresses preserved from iCal
- Driving, public transport and short walking options
- Leave-by times and previous-event journey chaining
- Three UK items, BBC Birmingham & Black Country articles and BBC Sport articles with compact source-derived RSS summaries
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

## Local and sport news

Local news uses the dedicated BBC Birmingham & Black Country RSS feed rather
than broad search results. Sport uses the BBC Sport RSS feed and prints in its
own section. Both require dated BBC article links and skip live pages, hub
pages, previews, videos and promotional headlines. Local stories may be fewer
than three when the feed has no suitable recent articles; unavailable news
sections are omitted. The control page has a Sport news toggle and a separate
sport story count (default 3). General UK news remains unchanged.

### Monthly repayments in commitments

`MONTHLY COMMITMENTS` includes monthly bill/subscription entries, instalment
payments from `data/subscriptions.json`, and `monthly_payment` on debts in
`data/finance_settings.json` (including a mortgage). It prints a separate
`REPAYMENTS DUE` subtotal and includes unpaid repayments in `REMAINING`.
Outstanding *balances* stay in `AMOUNTS OWED` and are not added to the monthly
total. Fully repaid entries (zero remaining balance) are omitted.

A repayment already in the `monthly` list is not added again when its name
matches, ignoring case and punctuation. If the display names differ, add
`"monthly_commitment_name": "Exact monthly list name"` to the instalment or
debt entry. Add `"match": ["bank transaction wording"]` to a repayment
entry if you want a transaction to mark this month's instalment as paid;
without a match, the receipt conservatively lists it as due. The paid check
uses the existing account transactions and the recorded repayment amount.
No repayment is automatically turned into a dated payday commitment: add an
individual or recurring date to `commitments` if it needs to affect the
before-payday allowance.

### Spending categories

Built-in merchant rules now recognise common entries such as supermarkets,
petrol, public transport, restaurants, utilities, rent, insurance, household
shops, entertainment and subscriptions. They apply to the 30-day category
trends and quarterly/yearly comparisons. A private
`data/finance_categories.json` still overrides them; for example:

```json
{
  "A SPECIFIC MERCHANT": "HOUSEHOLD"
}
```

The rules change category labels, not transaction totals. The finance receipt
prints up to three merchants in `CATEGORY CHECK - OTHER` when uncategorised
spending reaches £20 in the last 30 days. Person-to-person payments and
ambiguous merchant names intentionally remain `OTHER` until you add a private
rule based on what the purchase actually was. Do not put personal payee names
in the public repository.

## Receipt Control server address

`web_control/run_waitress.py` listens on `0.0.0.0:5050` by default. If startup
fails with `Address already in use`, check for an existing instance on macOS:

```bash
lsof -nP -iTCP:5050 -sTCP:LISTEN
```

Stop the process you recognise as an old Receipt Control server, or use another
port without editing the script:

```bash
RECEIPT_WEB_PORT=5051 python web_control/run_waitress.py
```

Use `RECEIPT_WEB_HOST=127.0.0.1` to bind only on this computer. Other socket
errors now include the address and a relevant diagnostic. The final line of the
Python traceback (`OSError: [Errno ...] ...`) determines which bind error
occurred.

The clarified merchants `LEMONWORLD` (coffee shop), `STIR STORE` (bar) and
`JOBGETHER.COM` (a cancelled subscription) have general category rules. Its
historical transaction remains a subscription expense, but this category rule
does not create a future commitment. Remove any cancelled Jobgether entry from
private `data/subscriptions.json` if one was entered there. Festival ticket
instalments remain entertainment spending; their monthly payment and outstanding
balance are shown separately when configured. Personal payee names and
unidentified merchants belong only in private category overrides.

For a purchase whose category depends on the *item* rather than the merchant,
put a one-off rule in the ignored `data/finance_categories.json`:

```json
{
  "transactions": [
    {"date": "YYYY-MM-DD", "amount": 22.00,
     "merchant": "EXAMPLE SHOP", "category": "GIFTS"}
  ]
}
```

A one-off rule matches the date, absolute amount and merchant text together.
It overrides merchant-wide categories for that transaction only. Merge it with
any existing private merchant rules; do not replace your whole file. If there
are two purchases at the same merchant for the same amount on the same day,
this format will match both and needs a more specific transaction identifier.
