# Thermal Receipt Printer — Complete Modular

This is the complete merged project based on `thermal_receipt_modular_v3`, with
the later calendar, news, finance, savings and savings-growth work folded
back into the project.

## Install and check

Use your project's Python environment and install all application dependencies:

```sh
python -m pip install -r requirements.txt
```

The RSS parser uses `defusedxml` to reject entity declarations. For development
checks, install `requirements-dev.txt` and run `python -m unittest discover -s tests`.
GitHub checks run tests, compilation, undefined-name checks and high-severity
security checks on Python 3.11 and 3.14. Offline `--preview`, `--health` and
`--validate` commands do not import the live printer/bank pipeline. Missing optional
private runtime files are permitted; malformed present files still report errors.
See [the code review notes](docs/codebase-review.md) for fixes and limitations.

## Physical receipts

1. Daily Information — weather + compact UK, BBC regional and BBC Sport headlines
2. Daily Actions — calendar events with locations, Villa match-day trains, to-do, deliveries, other requested checks
3. Food — daily recipe; Saturday plan/shopping; Sunday prep
4. Finance — only when requested

The **Receipt location** fields in Receipt Control set the name and region on
the information receipt, the weather coordinates, and the BBC local news feed
and heading. The default values reproduce the original Stirchley and
Birmingham output. Choose a BBC regional RSS feed under
`https://feeds.bbci.co.uk/news/` when changing area; the receipt still filters
out live blogs, hub pages and previews. UK headlines, BBC Sport and Aston
Villa match-day trains remain separate from the local-news location.
The automatic "Pay for therapy" checklist item appears only two or three days
before a dated therapy event in the calendar.
Receipt Control can also omit this automatic reminder when a matching outgoing
payment appears today or in the preceding two days. Under **Therapy payment
reminder**, set the bank payment reference (payee name as shown on the bank
transaction) and choose Monzo or HSBC. This private setting stays in the ignored
`data/receipt_settings.json`. Bank access failures leave the reminder visible.
The same completed payment also hides an exact "Pay for therapy." task in the
Google Doc for that receipt.
The therapy reference defaults to blank. Set it privately in Receipt Control;
existing saved local settings are retained. Finance receipts show a dedicated 30-day incoming
section: salary totals and payments, all other incoming payments, and the amount
remaining after outgoings. Salary/payroll descriptions are recognised automatically;
enter an employer bank reference under **Salary identification** if the bank uses a
different name.
Other incoming credits are grouped as rent received, Premium Bonds, friends or
family repayments, betting winnings, or other income. Each payment is listed
within the last 30 calendar days, including records supplied with a date instead
of a full timestamp. A bank connection must return the credit for it to appear.

## Added since modular v3

- Calendar locations print beneath each event when present; ordinary event directions are omitted
- Aston Villa home match train information remains on the receipt
- Three UK items, BBC Birmingham & Black Country articles and BBC Sport articles with compact headlines
- Optional news disappears if unavailable
- Finance uses £ formatting
- Upcoming payments are one line: name / amount / date
- Spending summaries use available bank records; unavailable historical baselines are omitted
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
without a match, the receipt conservatively lists it as due. A recognised
merchant can also be matched at the exact monthly payment amount.
The paid check uses the existing account transactions and the recorded repayment amount.
When a repayment has a `next_payment` or `due_date`, a debit with the same amount
within two days of that day of the month can also verify payment even if the
merchant wording differs. A transaction can verify only one commitment;
repayments without a scheduled date or matching merchant stay due.
An observed streaming subscription can be included at its latest charge amount
when a recent payment exists; an explicit monthly entry takes precedence.
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

## Printer connection

The daily receipt and web print actions use the configured network printer by
default. The live preview uses a virtual printer and never sends data to the
printer. To change the destination, set
`RECEIPT_PRINTER_HOST` and optionally `RECEIPT_PRINTER_PORT` in the environment
that launches the application. To return to USB printing, set
`RECEIPT_PRINTER_CONNECTION=usb` (USB IDs `0x0416:0x5011`). The standalone
`print_google_doc.py` has its own network connection setting. Reserve the
printer's address on the router to avoid a later address conflict.

## Receipt Control server address

Receipt Control now groups the main print actions at the top and links to
settings, routines, instalments and food shop on the same page. Its paper-width
preview can generate a full receipt using current sources without printing or
consuming one-shot requests. It stores the latest generated pages (including
charts) locally in the ignored `data/live_receipt_preview.json`, so they remain
available in the authenticated web interface while away from the printer.
Choose **Include finance** to run the finance page outside its usual schedule.
Generation happens in the background; the page updates when it finishes. You
can also switch to the last successful web-triggered print stored in the ignored
`data/last_web_receipt.json`. Pages without a captured result show clearly
labelled illustrative examples. A preview reflects its generation time, so it
may differ from a later print. Failed refreshes leave the previous saved preview
available. Preview errors are logged in `logs/web_preview.log`. Finance review fetches current bank transactions when
opened and shows the transaction behind each monthly payment match. The print
status reports whether the web print command is running, finished or failed;
the detailed diagnostic log is `logs/web_print.log`.

The control page also links to today's meal plan, a calendar map and Tesco
shopping review. You can choose today's recipe from the recipe library; that
updates the printed recipe and regenerates the plan's shopping items. Confirming
a recipe eaten records that fact separately from cooking and can be undone.
Calendar events and locations come from the read-only iCal feed; edit them in
your calendar. The map sends a selected event's location to Google Maps.

The food-shop editor saves a local list that replaces the Google Doc list on
the control page and the printed food-shop section. Reset returns to the Doc.
The Tesco review combines food-shop items and the current meal plan's shopping
items; it opens Tesco searches for product selection and keeps a weekly local checklist.
It cannot read or add products to your Tesco basket. Confirm each actual addition
on Tesco before marking it on the checklist. Monthly commitments can be edited
under their own section; instalment balances are edited separately.

Finance review includes a paid versus unverified commitments bar, 30-day
spending by category, and four seven-day spending bars. The figures come from
the same cleaned transactions and private category rules as the receipt; each
bar also has its exact amount in text. Instalment cards show repayment progress
when a total and remaining balance are available. The charts use local CSS
and require no external chart service.

The finance review also shows all observed outgoings from the current calendar
month, grouped by merchant, with each group's combined spend and an expandable
list of dates and individual amounts. Identical same-day payments without a
transaction ID remain separate; duplicated bank transaction IDs are removed.
Income, refunds, internal transfers and card repayments are excluded. This
calendar-month total is distinct from the rolling 30-day category chart and
from future commitments.

`web_control/run_waitress.py` listens on `127.0.0.1:5050` by default, so the
control page is available only on this computer. To access it from another
device, put it behind an HTTPS reverse proxy with authentication and set
`RECEIPT_WEB_SECURE_COOKIE=1`. If you deliberately bind to a LAN address,
set `RECEIPT_WEB_HOST` explicitly; plain HTTP on a shared network can expose
the password and session. The control page requires a form token for each
change and limits failed sign-ins to five per client address in 15 minutes.
The limit is held in the server process and resets when it restarts.

While the Waitress server is running, it starts one full receipt print at
**03:00 UK time** every day (including daylight saving changes). Starting the
server after 03:00 waits until the next day. If another print is running at
03:00, it retries every five minutes that day. The date of a launched scheduled
job is kept in `data/.scheduled_print_date` so a server restart does not print
twice. The usual receipt rules still decide whether to include finance. Print
results appear in `data/web_print_status.json` and `logs/web_print.log`.

If startup
fails with `Address already in use`, check for an existing instance on macOS:

```bash
lsof -nP -iTCP:5050 -sTCP:LISTEN
```

Stop the process you recognise as an old Receipt Control server, or use another
port without editing the script:

```bash
RECEIPT_WEB_PORT=5051 python web_control/run_waitress.py
```

Other socket errors include the address and a relevant diagnostic. The final line of the
Python traceback (`OSError: [Errno ...] ...`) determines which bind error
occurred.

Category rules classify historical transactions without creating future
commitments. Remove cancelled monthly entries from the private subscription
file. Instalment spending and outstanding balances are shown separately when
configured. Personal payee names belong only in private category overrides.

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


### HTML template formatting

Templates use four-space indentation with the Jinja-aware settings in `.djlintrc`.
Install `requirements-dev.txt`, then run:

```bash
python tools/format_templates.py
python tools/format_templates.py --check
```

Inline scripts and styles are excluded from HTML reformatting to preserve their contents.
Receipt text in `pre` blocks and editable textarea contents retain their whitespace.


### Shared boundaries and interface checks

The interface uses a shared theme, responsive navigation and a collapsible More tools menu.
Display preferences include larger text, higher contrast and reduced motion. Form validation
opens hidden sections and focuses the first invalid field; submission feedback is announced.

`storage.PrivateStore` provides locked, validated, atomic updates for migrated private state.
Invalid files are retained for recovery rather than overwritten. `finance.money` handles
Decimal parsing and penny rounding at shared calculation boundaries; legacy provider and
receipt dictionaries remain compatible. Typed models normalise transactions, commitments,
deliveries and source observations. Delivery parsing and bank collection now have separate
service modules with injected dependencies.

Source observations distinguish fresh, cached, partial, unavailable and disabled results.
Monthly finance observations retain the collection scope without account identifiers.
Older observations with no scope are labelled accordingly, and a mid-month observation is
never marked as covering a whole month. CI runs Python 3.11–3.14 tests, lint, security checks
and template formatting checks. The template wrapper preserves excluded scripts and styles.

### Receipt generation and interface regression checks

Scheduled printing, manual printing and previews share the bounded child supervisor
and lifecycle status writer. Workers release only a lock bearing their own PID.
The shared receipt builder saves its buffered output before opening hardware; a failed
printer connection leaves the generated copy available. A successful socket send does
not certify that paper was produced.

The loading panel shows actual stage names, recently completed steps and elapsed time.
The moving indicator means work is in progress; the stage count is not a time estimate.
Expand **Generation timings** to find slow collection stages. Timings contain stage
names and durations only, and are bounded to the latest 80 stages of the job.

PrivateStore supports explicit schema versions and sequential migrations. Finance
planning and subscriptions are versioned stores: legacy data is migrated in memory and persisted
on its next successful update. Unsupported future versions and damaged files are
preserved instead of overwritten. Other private stores retain their existing formats
until an explicit migration is introduced; take a private backup before upgrades.

The receipt uses shared width-safe money columns, compact savings indicators, dashed
rules and a local-time footer identifying cached or incomplete source checks. Delivery
items retain their confirmation identities while timing appears below the item group.
Source fetching remains outside the extracted calendar and delivery rendering module.

Browser CI exercises manual bin dates, adding a commitment, confirming a delivery and
opening a generated preview at four viewport widths. The harness uses real Flask routes
and templates in an isolated temporary project; external collection and hardware are
replaced by fixtures. It communicates through standard input/output rather than exposing
a fixture login endpoint on the production server. To run locally after installing
Playwright and Chromium:

```bash
npm install --no-save playwright@1.56.1
npx playwright install chromium
node tools/browser_smoke.cjs
```

Anonymous integration examples are in `tests/fixtures/receipt_integrations.json`.
Timezone regressions cover midnight and the autumn BST/GMT transition.
