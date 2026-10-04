from __future__ import annotations
from finance.investments import (
    load_investments,
    investment_totals,
    investment_age_days,
    investment_snapshot,
)
from datetime import date, datetime, timedelta
from calendar import monthrange
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from finance_trends import (
    load_rules, category_trends, uncategorised_merchants,
    clean_spending_transactions, spending_total,
    debug_spending_transactions,
    completed_periods_to_save, period_analysis, save_snapshot,
    load_snapshot, add_savings_growth_to_analysis,
    savings_growth_receipt_lines, period_receipt_lines, everyday_spending_transactions,
)
from finance_period_helpers import previous_period_label
from savings_runway import (
    load_savings, savings_totals, savings_receipt_lines,
    savings_snapshot,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = PROJECT_ROOT / "data" / "finance_categories.json"
HISTORY_FILE = PROJECT_ROOT / "data" / "finance_history.json"
SAVINGS_FILE = PROJECT_ROOT / "data" / "savings.json"

FINANCE_SETTINGS_FILE = PROJECT_ROOT / "data" / "finance_settings.json"

INVESTMENTS_FILE = (
    PROJECT_ROOT
    / "data"
    / "investments.json"
)

# Keep this True while validating the corrected 30-day calculation.
# Set it to False once the console total matches the banking data you expect.
DEBUG_SPENDING = True

def _money(v):
    v = float(v or 0)
    return f"-£{abs(v):,.2f}" if v < 0 else f"£{v:,.2f}"

def print_line(
    printer,
    char="-",
    width=40,
):
    printer.text(
        (char * width) + "\n"
    )

def _decimal(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
        if not amount.is_finite():
            raise ValueError("Non-finite amount")
        return amount
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid finance amount: {value!r}") from exc


def _amount_rows(label, value, width=40):
    label = str(label).upper().strip()
    amount = _decimal(value)
    formatted = (f"-£{abs(amount):,.2f}" if amount < 0
                 else f"£{amount:,.2f}")
    if len(label) + len(formatted) + 1 <= width:
        return [label + formatted.rjust(width - len(label))]
    from textwrap import wrap
    rows = wrap(label, width=width, break_long_words=True)
    rows.append(formatted.rjust(width))
    return rows


def _amount_line(label, value):
    return _amount_rows(label, value)[0]


def _recent_incoming_items(items, today):
    cutoff = today - timedelta(days=29)
    recent = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        paid_on = item.get("date")
        try:
            if isinstance(paid_on, datetime):
                paid_on = paid_on.date()
            elif isinstance(paid_on, str):
                paid_on = date.fromisoformat(paid_on[:10])
            amount = _decimal(item.get("amount"))
        except (ValueError, TypeError):
            continue
        if isinstance(paid_on, date) and cutoff <= paid_on <= today and amount > 0:
            recent.append({"date": paid_on, "name": str(item.get("name") or "INCOMING PAYMENT"),
                           "category": str(item.get("category") or "OTHER IN"),
                           "amount": amount})
    return sorted(recent, key=lambda item: (item["date"], item["name"]), reverse=True)


def print_incoming_payments(printer, left, line, summary, total_outgoings, today):
    """Show every reported incoming bank payment in the same 30-day window."""
    salary = _recent_incoming_items(summary.get("salary_incomings"), today)
    other = _recent_incoming_items(summary.get("other_incomings"), today)
    salary_total = sum((item["amount"] for item in salary), Decimal(0))
    other_total = sum((item["amount"] for item in other), Decimal(0))
    total = salary_total + other_total

    printer.text("\n")
    left(printer, "INCOMING / LAST 30 DAYS [BANK TX]")
    line(printer, "-")
    if summary.get("bank_data_status", "complete") != "complete":
        left(printer, "BANK DATA INCOMPLETE")
        left(printer, "INCOMING NOT VERIFIED")
        if not salary and not other:
            return
    values = [("SALARY", salary_total), ("OTHER IN", other_total),
              ("KNOWN IN" if summary.get("bank_data_status", "complete") != "complete"
               else "TOTAL IN", total)]
    if summary.get("bank_data_status", "complete") == "complete":
        values.append(("AFTER OUTGOINGS", total - _decimal(total_outgoings)))
    for label, value in values:
        for row in _amount_rows(label, value):
            left(printer, row)

    line(printer, "-")
    left(printer, f"SALARY PAYMENTS ({len(salary)})")
    for item in salary:
        label = f"{item['date']:%d %b} {item['name']}"
        for row in _amount_rows(label, item["amount"]):
            left(printer, row)

    line(printer, "-")
    left(printer, f"OTHER INCOMING PAYMENTS ({len(other)})")
    categories = ("RENT RECEIVED", "PREMIUM BONDS", "FRIENDS / FAMILY",
                  "BET WINNINGS", "OTHER IN")
    for category in categories:
        items = [item for item in other if item["category"] == category]
        if not items:
            continue
        for row in _amount_rows(f"{category} ({len(items)})",
                                sum((item["amount"] for item in items), Decimal(0))):
            left(printer, row)
        for item in items:
            label = f"{item['date']:%d %b} {item['name']}"
            for row in _amount_rows(label, item["amount"]):
                left(printer, row)


def load_finance_settings(path=FINANCE_SETTINGS_FILE):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Finance settings must be an object")
    return data


def _calendar_occurrence(anchor, today, repeat):
    """First occurrence on/after today, anchored to the original calendar day."""
    if repeat == "once":
        return anchor if anchor >= today else None
    if repeat == "monthly":
        months = max(0, (today.year - anchor.year) * 12 + today.month - anchor.month)
        while True:
            year, month_zero = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
            candidate = date(year, month_zero + 1,
                             min(anchor.day, monthrange(year, month_zero + 1)[1]))
            if candidate >= today and candidate >= anchor:
                return candidate
            months += 1
    if repeat == "yearly":
        year = max(anchor.year, today.year)
        while True:
            candidate = date(year, anchor.month,
                             min(anchor.day, monthrange(year, anchor.month)[1]))
            if candidate >= today and candidate >= anchor:
                return candidate
            year += 1
    raise ValueError(f"Unsupported payment repeat: {repeat!r}")


def _due_commitments(settings, today, payday):
    due = []
    for item in settings.get("commitments", []):
        anchor = date.fromisoformat(item["due_date"])
        repeat = item.get("repeat", "once")
        occurrence = _calendar_occurrence(anchor, today, repeat)
        while occurrence is not None and occurrence < payday:
            due.append({**item, "due_date": occurrence.isoformat(),
                        "amount": _decimal(item["amount"])})
            if repeat == "once":
                break
            occurrence = _calendar_occurrence(anchor, occurrence + timedelta(days=1), repeat)
    return sorted(due, key=lambda item: item["due_date"])


def _forecast_events(events, today, end):
    upcoming = []
    for item in events:
        anchor = date.fromisoformat(item["date"])
        repeat = item.get("repeat", "once")
        occurrence = _calendar_occurrence(anchor, today, repeat)
        while occurrence is not None and occurrence <= end:
            upcoming.append({**item, "date": occurrence.isoformat()})
            if repeat == "once":
                break
            occurrence = _calendar_occurrence(anchor, occurrence + timedelta(days=1), repeat)
    return sorted(upcoming, key=lambda item: item["date"])


def calculate_debt_and_payday(cash, amex, instalments, settings, today):
    debts = [{"name": "AMEX", "type": "credit_card", "balance": _decimal(amex),
              "source": "B"}]
    existing_names = {"amex"}
    for item in instalments:
        balance = item.get("remaining_balance")
        if balance is None:
            continue
        name = str(item.get("name", "INSTALMENT"))
        if name.casefold() in existing_names:
            continue
        existing_names.add(name.casefold())
        debts.append({"name": name, "type": "payment_plan", "balance": _decimal(balance),
                      "monthly_payment": item.get("amount"), "source": "F"})
    for item in settings.get("debts", []):
        name = str(item["name"])
        if name.casefold() in existing_names:
            continue
        existing_names.add(name.casefold())
        debts.append({**item, "balance": _decimal(item["balance"]), "source": "F"})
    if any(debt["balance"] < 0 for debt in debts):
        raise ValueError("Debt balance cannot be negative")
    short = sum((d["balance"] for d in debts if d.get("type") != "mortgage"), Decimal(0))
    long = sum((d["balance"] for d in debts if d.get("type") == "mortgage"), Decimal(0))
    result = {"debts": debts, "short_term": short, "long_term": long,
              "net_liquid": _decimal(cash) - short}
    if settings.get("next_payday"):
        payday = _calendar_occurrence(
            date.fromisoformat(settings["next_payday"]), today + timedelta(days=1),
            settings.get("payday_repeat", "once")
        )
        days = (payday - today).days if payday is not None else 0
        if days > 0:
            commitments = _due_commitments(settings, today, payday)
            committed = sum((item["amount"] for item in commitments), Decimal(0))
            buffer = _decimal(settings.get("emergency_buffer", 0))
            safe = _decimal(cash) - committed - buffer
            result.update(payday=payday, days=days, commitments=commitments,
                          committed=committed, buffer=buffer, safe=safe,
                          daily=safe / days)
    return result


def print_integrated_finance(
    printer,
    left,
    line,
    balances,
    transactions,
    direct_debits=None,
    standing_orders=None,
    subscriptions=None,
    spending_summary=None,
    instalments=None,
    finance_settings_file=FINANCE_SETTINGS_FILE,
    today=None,
    commitment_status=None,
):

    direct_debits = (
        direct_debits or []
    )

    standing_orders = (
        standing_orders or []
    )

    subscriptions = (
        subscriptions or []
    )

    spending_summary = (
        spending_summary or {}
    )

    transactions = (
        transactions or []
    )

    # ==========================================
    # BALANCES
    # ==========================================

    hsbc = float(
        balances
        .get("HSBC", {})
        .get("available", 0)
        or 0
    )

    monzo = float(
        balances
        .get("MONZO", {})
        .get("available", 0)
        or 0
    )

    amex = float(
        balances
        .get("AMEX", {})
        .get("current", 0)
        or 0
    )

    available_cash = hsbc + monzo
    instalments = instalments or []
    today = today or datetime.now(ZoneInfo("Europe/London")).date()
    finance_settings = load_finance_settings(finance_settings_file)
    debt_summary = calculate_debt_and_payday(
        available_cash, amex, instalments, finance_settings, today
    )

    # ==========================================
    # SAVINGS
    # ==========================================

    savings_data = (
        load_savings(
            SAVINGS_FILE
        )
    )

    from finance.wealth_history import capture_local, review as wealth_review, apply_latest, receipt_lines as wealth_lines
    investment_data = load_investments(INVESTMENTS_FILE)
    wealth = None
    try:
        capture_local(savings_data, investment_data, today)
        wealth = wealth_review(today)
        savings_data, investment_data = apply_latest(savings_data, investment_data, wealth)
    except (ValueError, OSError, KeyError, TypeError):
        pass

    st = savings_totals(
        savings_data
    )

    from finance.projection import build_projection
    status = commitment_status or {"monthly": subscriptions, "yearly": []}
    projection = build_projection(balances, transactions, status["monthly"], status.get("yearly", []),
                                  finance_settings, today, st["runway_accessible"],
                                  spending_summary.get("bank_data_status", "complete"))
    if projection["valid"] and projection["payday"]:
        debt_summary.update(payday=projection["payday"], days=(projection["payday"] - today).days,
                            committed=projection["before_payday_total"], buffer=projection["buffer"],
                            safe=projection["safe_before_payday"], daily=projection["per_day_before_payday"])
    else:
        debt_summary.pop("payday", None)

    net_cash = available_cash - float(debt_summary["short_term"]) + st["net_cash"]

    # ==========================================
    # INVESTMENTS
    # ==========================================

    investment_summary = (
        investment_totals(
            investment_data
        )
    )

    investment_age = (
        investment_age_days(
            investment_data
        )
    )

    # ==========================================
    # SPENDING
    # ==========================================

    clean_transactions = clean_spending_transactions(
        transactions
    )

    everyday_transactions = (
        everyday_spending_transactions(
            clean_transactions
        )
    )

    # Everything genuinely spent,
    # including rent and bills.
    total_outgoings = spending_total(
        clean_transactions,
        days=30,
    )

    # Variable/day-to-day spending.
    last30 = spending_total(
        everyday_transactions,
        days=30,
    )

    fixed_commitments = max(
        0.0,
        total_outgoings - last30,
    )

    if DEBUG_SPENDING:
        debug_spending_transactions(
            clean_transactions,
            days=30,
        )

    # ==========================================
    # HEADER
    # ==========================================

    line(
        printer,
        "=",
    )

    printer.set(
        bold=True,
        align="center",
    )

    printer.text(
        "FINANCE\n"
    )

    printer.set(
        bold=False,
        align="left",
    )

    line(
        printer,
        "=",
    )

    # B = bank data; F = stored file; C = arithmetic; E = estimate.
    left(printer, "B BANK  F FILE  C CALC  E ESTIMATE")
    printer.text("\n")
    left(printer, "CASH NOW")
    print_line(printer)
    for label, value in (("HSBC", hsbc), ("MONZO", monzo)):
        left(printer, _amount_line(f"{label} [B]", value))
    print_line(printer)
    left(printer, _amount_line("AVAILABLE CASH [C]", available_cash))

    printer.text("\n")
    left(printer, "AMOUNTS OWED")
    print_line(printer)
    for debt in debt_summary["debts"]:
        if debt["balance"]:
            for row in _amount_rows(f"{debt['name']} [{debt['source']}]", debt["balance"]):
                left(printer, row)
            if debt.get("monthly_payment") is not None:
                left(printer, _amount_line("  MONTHLY [F]", debt["monthly_payment"]))
    print_line(printer)
    left(printer, _amount_line("SHORT-TERM DEBT [C]", debt_summary["short_term"]))
    left(printer, _amount_line("NET LIQUID [C]", debt_summary["net_liquid"]))
    if debt_summary["long_term"]:
        left(printer, _amount_line("LONG-TERM DEBT [C]", debt_summary["long_term"]))
    for debt in debt_summary["debts"]:
        if debt.get("original_amount") is not None:
            repaid = max(Decimal(0), _decimal(debt["original_amount"]) - debt["balance"])
            for row in _amount_rows(debt["name"] + " REPAID [C]", repaid):
                left(printer, row)

    printer.text("\n")
    left(printer, "UNTIL PAYDAY [E]")
    print_line(printer)
    if debt_summary.get("payday"):
        reviewed_on = finance_settings.get("reviewed_on")
        if reviewed_on:
            reviewed = date.fromisoformat(reviewed_on)
            age = (today - reviewed).days
            left(printer, f"MANUAL INPUTS CHECKED {reviewed:%d %b %Y}".upper())
            if age < 0 or age > 30:
                left(printer, "! REVIEW PAYMENT DATES / AMOUNTS")
        else:
            left(printer, "! MANUAL INPUTS NOT REVIEWED")
        left(printer, f"{debt_summary['payday']:%d %b %Y} | {debt_summary['days']} DAYS")
        left(printer, _amount_line("DATED PAYMENTS [C]", debt_summary["committed"]))
        left(printer, _amount_line("BUFFER [F]", debt_summary["buffer"]))
        print_line(printer)
        left(printer, _amount_line("SAFE TO SPEND [E]", debt_summary["safe"]))
        left(printer, _amount_line("PER DAY [E]", debt_summary["daily"]))
        if debt_summary["safe"] < 0:
            left(printer, "! PAYMENTS EXCEED CASH")
        minimum = finance_settings.get("minimum_balance_warning")
        if minimum is not None and debt_summary["safe"] < _decimal(minimum):
            left(printer, "! BELOW MINIMUM BALANCE")
        cutoff = _decimal(finance_settings.get("large_payment_threshold", 250))
        for item in debt_summary["commitments"]:
            if item["amount"] >= cutoff:
                left(printer, f"DUE {item['due_date'][5:]}: {item['name'][:26]}")
                left(printer, _amount_line("  PAYMENT [F]", item["amount"]))
    else:
        left(printer, "SET NEXT_PAYDAY FOR FORECAST")

    if st["accounts"]:
        printer.text("\n")
        left(printer, "SAVINGS [F]")
        print_line(printer)
        for account in st["accounts"]:
            for row in _amount_rows(f"{account['name']} [F]", account["balance"]):
                left(printer, row)
        left(printer, _amount_line("NET CASH + SAVINGS [C]", net_cash))

    try:
        from finance.savings_goals import review as goal_review, receipt_lines as goal_lines
        for text in goal_lines(goal_review(wealth,on=today)):
            left(printer,text)
    except (ValueError,OSError,KeyError,TypeError):
        left(printer,'SAVINGS GOALS UNAVAILABLE')
    if wealth:
        for text in wealth_lines(wealth):
            left(printer, text)

    # ==========================================
    # INVESTMENTS
    # ==========================================

    if investment_data[
        "accounts"
    ]:

        printer.text("\n")

        left(
            printer,
            "INVESTMENTS [F]",
        )

        line(
            printer,
            "-",
        )

        for account in (
            investment_data[
                "accounts"
            ]
        ):

            name = str(
                account.get(
                    "name",
                    "INVESTMENT",
                )
            ).upper()[:24]

            try:
                value = float(
                    account.get(
                        "value",
                        0,
                    )
                    or 0
                )

            except (
                TypeError,
                ValueError,
            ):
                value = 0.0

            for row in _amount_rows(f"{name} [F]", value):
                left(printer, row)

        line(
            printer,
            "-",
        )

        left(printer, _amount_line("TOTAL [C]", investment_summary["value"]))
        manual_valuations = wealth and any(a["kind"] == "investment" and a["latest"]["source"] == "manual"
                                          for a in wealth["accounts"])
        contributions_known = all("contributions" in a for a in investment_data["accounts"])
        if contributions_known and not manual_valuations:
            for label, value in (("CONTRIBUTED", investment_summary["contributions"]),
                                 ("GAIN / LOSS", investment_summary["gain"])):
                left(printer, _amount_line(f"{label} [C]", value))
            gain_pct = investment_summary["gain_pct"]
            if gain_pct is not None:
                left(printer, f"RETURN {gain_pct:+.1f}%")
        else:
            left(printer, "SEE DATED HISTORY FOR BALANCE CHANGES")

        if (
            investment_age is not None
            and investment_age > 30
        ):
            left(
                printer,
                (
                    f"VALUE {investment_age} "
                    "DAYS OLD"
                ),
            )

    # ==========================================
    # SPENDING
    # ==========================================

    printer.text("\n")

    from finance.premium_bonds import receipt_lines as premium_bond_lines
    try:
        bond_lines = premium_bond_lines(today)
    except (ValueError, OSError):
        bond_lines = ["PREMIUM BONDS HISTORY UNAVAILABLE"]
    for row in bond_lines:
        left(printer, row)
    left(
        printer,
        "SPENDING - BANK TX [C]",
    )

    print_line(
        printer,
        "-",
    )
    if spending_summary.get("bank_data_status", "complete") != "complete":
        left(printer, "BANK DATA INCOMPLETE")

    for label, value in (
        ("EVERYDAY SPEND", last30),
        ("FIXED COMMITMENTS", fixed_commitments),
        ("TOTAL OUTGOINGS", total_outgoings),

    ):
        left(printer, _amount_line(label, value))

    print_incoming_payments(printer, left, print_line, spending_summary,
                            total_outgoings, today)

    if any(finance_settings.get(field) is not None for field in ('hsbc_emergency_reserve','physical_cash_target','salary_savings_target')):
        try:
            from finance.salary_plan import build as build_salary_plan
            salary_goals=goal_review(wealth,on=today)
            allocation=build_salary_plan(spending_summary.get('salary_incomings',[]),transactions,balances,projection,finance_settings,salary_goals,today)
            printer.text("\n")
            left(printer,'SALARY ALLOCATION [E]')
            print_line(printer)
            left(printer,_amount_line('HSBC RESERVE TARGET',allocation['reserve']['bank']))
            left(printer,_amount_line('PHYSICAL CASH TARGET',allocation['reserve']['target']))
            if allocation['reserve']['held'] is not None:
                left(printer,_amount_line('PHYSICAL CASH RECORDED',allocation['reserve']['held']))
            left(printer,_amount_line('CASH TOP-UP RESERVED',allocation['reserve']['gap']))
            if allocation['valid']:
                left(printer,_amount_line('SALARY AVAILABLE TO PLAN',allocation['available']))
                for bucket in allocation['buckets']:
                    for row in _amount_rows(bucket['name'].upper(),bucket['amount']): left(printer,row)
                left(printer,'PLAN ONLY / NO TRANSFERS MADE')
            else:
                left(printer,'ALLOCATION NEEDS SALARY / COMPLETE DATA')
                if allocation['reserve']['hsbc_gap']:
                    left(printer,_amount_line('HSBC BELOW RESERVE BY',allocation['reserve']['hsbc_gap']))
        except (ValueError,OSError,KeyError,TypeError): left(printer,'SALARY ALLOCATION UNAVAILABLE')

    # ==========================================
    # CATEGORY TRENDS
    # ==========================================

    rules = load_rules(
        RULES_FILE
    )

    trends = category_trends(
        clean_transactions,
        rules,
        minimum_current_spend=20.0,
    )

    unknown = uncategorised_merchants(
        clean_transactions, rules, as_of=today,
        minimum_amount=20.0, limit=3,
    )
    if unknown:
        printer.text("\n")
        left(printer, "CATEGORY CHECK - OTHER [BANK TX]")
        print_line(printer, "-")
        for item in unknown:
            for row in _amount_rows(item["merchant"][:24], item["amount"]):
                left(printer, row)



    current_categories = [
        row for row in trends if row["current"] > 0
    ][:8]
    if current_categories:
        printer.text("\n")
        left(printer, "SPENDING BY CATEGORY / 30 DAYS")
        print_line(printer, "-")
        for row in current_categories:
            for amount_row in _amount_rows(row["category"], row["current"]):
                left(printer, amount_row)

    # ==========================================
    # RUNWAY
    # ==========================================

    printer.text("\n")
    left(printer, "RUNWAY / DATED PAYMENTS [E]")
    print_line(printer)
    left(printer, "ASSUMES NO FUTURE INCOME")
    left(printer, _amount_line("EVERYDAY PER DAY", projection["daily"]))
    upcoming_total = sum((item["amount"] for item in projection["upcoming"]), Decimal(0))
    left(printer, _amount_line("LISTED PAYMENTS / 30D", upcoming_total))
    for label, days in (("CASH RUNWAY", projection["cash_days"]),
                        ("WITH ACCESSIBLE SAVINGS", projection["total_days"])):
        from finance.projection import format_runway
        value = (format_runway(days, today) if days is not None else
                 "Over " + projection["horizon_duration"] if projection["valid"] else "Unavailable")
        left(printer, label)
        from textwrap import wrap
        for row in wrap(value.upper(), width=40):
            left(printer, row.rjust(40))
        run_out = projection["cash_run_out_date" if label == "CASH RUNWAY" else "total_run_out_date"]
        if run_out:
            left(printer, f"PROJECTED SHORTFALL: {run_out:%d %b %Y}".upper())
        elif projection["valid"]:
            left(printer, f"NO SHORTFALL THROUGH {projection['horizon_end_date']:%d %b %Y}".upper())
    if projection["buffer"] > 0:
        left(printer, "DATES PROTECT YOUR CASH BUFFER")
    from textwrap import wrap
    for warning in projection["warnings"]:
        for row in wrap(warning.upper(), width=40):
            left(printer, row)

    # ==========================================
    # QUARTER / YEAR REVIEW
    # ==========================================

    for (
        kind,
        period_date,
    ) in completed_periods_to_save(
        today
    ):

        analysis = (
            period_analysis(
                clean_transactions,
                rules,
                kind,
                period_date,
            )
        )

        current_savings = (
            savings_snapshot(
                savings_data
            )
        )

        prev_label = (
            previous_period_label(
                kind,
                analysis["label"],
            )
        )

        previous = (
            load_snapshot(
                HISTORY_FILE,
                prev_label,
            )
        )

        analysis = (
            add_savings_growth_to_analysis(
                analysis,
                current_savings,
                previous,
            )
        )

        current_investments = (
            investment_snapshot(
                investment_data
            )
        )

        save_snapshot(
            HISTORY_FILE,
            analysis,
            investment_snapshot=
                current_investments,
        )

        line(
            printer,
            "=",
        )

        left(printer, "PERIOD REVIEW [C]: BANK TX + FILE")
        for text in (
            period_receipt_lines(
                analysis
            )
        ):
            left(
                printer,
                text,
            )

        for text in (
            savings_growth_receipt_lines(
                analysis
            )
        ):
            left(
                printer,
                text,
            )

    # Forward cashflow is based only on explicitly dated events.
    events = finance_settings.get("forecast_events", [])
    if events:
        end = today + timedelta(days=30)
        upcoming = _forecast_events(events, today, end)
        change = sum((_decimal(item["amount"]) for item in upcoming), Decimal(0))
        printer.text("\n")
        left(printer, "NEXT 30 DAYS - LISTED EVENTS")
        print_line(printer)
        left(printer, _amount_line("KNOWN CASH CHANGE [C]", change))
        left(printer, _amount_line("CASH AFTER EVENTS [E]", _decimal(available_cash) + change))

    goals = finance_settings.get("savings_goals", [])
    if goals:
        printer.text("\n")
        left(printer, "SAVINGS GOALS [F]")
        print_line(printer)
        for goal in goals:
            for row in _amount_rows(str(goal["name"]), goal["saved"]):
                left(printer, row)
            left(printer, _amount_line("  TARGET", goal["target"]))

    line(printer, "=")
