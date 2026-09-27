from __future__ import annotations
from finance.investments import (
    load_investments,
    investment_totals,
    investment_age_days,
    investment_snapshot,
)
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from finance_trends import (
    load_rules, category_trends, receipt_trend_lines,
    clean_spending_transactions, spending_total, usual_30_day_spend,
    debug_spending_transactions,
    completed_periods_to_save, period_analysis, save_snapshot,
    load_snapshot, add_savings_growth_to_analysis,
    savings_growth_receipt_lines, period_receipt_lines, everyday_spending_transactions,
)
from finance_period_helpers import previous_period_label
from savings_runway import (
    load_savings, savings_totals, savings_receipt_lines,
    runway_receipt_lines, savings_snapshot,
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


def load_finance_settings(path=FINANCE_SETTINGS_FILE):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Finance settings must be an object")
    return data


def calculate_debt_and_payday(cash, amex, instalments, settings, today):
    debts = [{"name": "AMEX", "type": "credit_card", "balance": _decimal(amex)}]
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
                      "monthly_payment": item.get("amount")})
    for item in settings.get("debts", []):
        name = str(item["name"])
        if name.casefold() in existing_names:
            continue
        existing_names.add(name.casefold())
        debts.append({**item, "balance": _decimal(item["balance"])})
    if any(debt["balance"] < 0 for debt in debts):
        raise ValueError("Debt balance cannot be negative")
    short = sum((d["balance"] for d in debts if d.get("type") != "mortgage"), Decimal(0))
    long = sum((d["balance"] for d in debts if d.get("type") == "mortgage"), Decimal(0))
    result = {"debts": debts, "short_term": short, "long_term": long,
              "net_liquid": _decimal(cash) - short}
    if settings.get("next_payday"):
        payday = date.fromisoformat(settings["next_payday"])
        days = (payday - today).days
        if days > 0:
            commitments = [{**item, "amount": _decimal(item["amount"])}
                           for item in settings.get("commitments", [])
                           if today <= date.fromisoformat(item["due_date"]) < payday]
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

    st = savings_totals(
        savings_data
    )

    net_cash = available_cash - float(debt_summary["short_term"]) + st["net_cash"]

    # ==========================================
    # INVESTMENTS
    # ==========================================

    investment_data = (
        load_investments(
            INVESTMENTS_FILE
        )
    )

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

    # Historical comparison should compare
    # like-for-like everyday spending.
    usual = usual_30_day_spend(
        everyday_transactions
    )

    fixed_commitments = max(
        0.0,
        total_outgoings - last30,
    )

    monthly_spend = (
        usual
        or last30
    )

    overall_change = (
        (
            (last30 - usual)
            / usual
            * 100
        )
        if usual > 0
        else None
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

    # Cash, debt and payday each answer a different question.
    left(printer, "CASH NOW")
    print_line(printer)
    for label, value in (("HSBC", hsbc), ("MONZO", monzo)):
        left(printer, _amount_line(label, value))
    print_line(printer)
    left(printer, _amount_line("AVAILABLE CASH", available_cash))

    printer.text("\n")
    left(printer, "AMOUNTS OWED")
    print_line(printer)
    for debt in debt_summary["debts"]:
        if debt["balance"]:
            for row in _amount_rows(debt["name"], debt["balance"]):
                left(printer, row)
            if debt.get("monthly_payment") is not None:
                left(printer, _amount_line("  MONTHLY", debt["monthly_payment"]))
    print_line(printer)
    left(printer, _amount_line("SHORT-TERM DEBT", debt_summary["short_term"]))
    left(printer, _amount_line("NET LIQUID", debt_summary["net_liquid"]))
    if debt_summary["long_term"]:
        left(printer, _amount_line("LONG-TERM DEBT", debt_summary["long_term"]))
    for debt in debt_summary["debts"]:
        if debt.get("original_amount") is not None:
            repaid = max(Decimal(0), _decimal(debt["original_amount"]) - debt["balance"])
            for row in _amount_rows(debt["name"] + " REPAID", repaid):
                left(printer, row)

    printer.text("\n")
    left(printer, "UNTIL PAYDAY")
    print_line(printer)
    if debt_summary.get("payday"):
        left(printer, f"{debt_summary['payday']:%d %b %Y} | {debt_summary['days']} DAYS")
        left(printer, _amount_line("DATED PAYMENTS DUE", debt_summary["committed"]))
        left(printer, _amount_line("BUFFER", debt_summary["buffer"]))
        print_line(printer)
        left(printer, _amount_line("SAFE TO SPEND", debt_summary["safe"]))
        left(printer, _amount_line("PER DAY", debt_summary["daily"]))
        if debt_summary["safe"] < 0:
            left(printer, "! PAYMENTS EXCEED CASH")
        minimum = finance_settings.get("minimum_balance_warning")
        if minimum is not None and debt_summary["safe"] < _decimal(minimum):
            left(printer, "! BELOW MINIMUM BALANCE")
        cutoff = _decimal(finance_settings.get("large_payment_threshold", 250))
        for item in debt_summary["commitments"]:
            if item["amount"] >= cutoff:
                left(printer, f"DUE {item['due_date'][5:]}: {item['name'][:26]}")
                left(printer, _amount_line("  PAYMENT", item["amount"]))
    else:
        left(printer, "SET NEXT_PAYDAY FOR FORECAST")

    if st["accounts"]:
        printer.text("\n")
        left(printer, "SAVINGS")
        print_line(printer)
        for account in st["accounts"]:
            for row in _amount_rows(account["name"], account["balance"]):
                left(printer, row)
        left(printer, _amount_line("NET CASH + SAVINGS", net_cash))

    # ==========================================
    # INVESTMENTS
    # ==========================================

    if investment_data[
        "accounts"
    ]:

        printer.text("\n")

        left(
            printer,
            "INVESTMENTS",
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

            for row in _amount_rows(name, value):
                left(printer, row)

        line(
            printer,
            "-",
        )

        for label, value in (
            ("TOTAL", investment_summary["value"]),
            ("CONTRIBUTED", investment_summary["contributions"]),
            ("GAIN / LOSS", investment_summary["gain"]),
        ):
            left(printer, _amount_line(label, value))
        gain_pct = investment_summary["gain_pct"]
        if gain_pct is not None:
            left(printer, f"RETURN {gain_pct:+.1f}%")

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

    left(
        printer,
        "SPENDING - LAST 30 DAYS",
    )

    print_line(
        printer,
        "-",
    )

    for label, value in (
        ("EVERYDAY SPEND", last30),
        ("FIXED COMMITMENTS", fixed_commitments),
        ("TOTAL OUTGOINGS", total_outgoings),
        ("3 MONTH AVG", usual),
    ):
        left(printer, _amount_line(label, value))
    if usual > 0:
        left(printer, f"CHANGE {(last30 - usual) / usual * 100:+.1f}%")

    # Incomings are sourced from the existing 30-day account summary.
    incoming = spending_summary.get("total_incoming_30_days")
    if incoming is not None:
        print_line(printer, "-")
        left(printer, _amount_line("INCOME - 30 DAYS", incoming))
        left(printer, _amount_line("INCOME LESS OUTGOINGS", float(incoming) - total_outgoings))

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

    if trends:

        line(
            printer,
            "-",
        )

        for text in (
            receipt_trend_lines(
                trends
            )
        ):

            if (
                text
                == "LARGEST CHANGES"
            ):
                break

            text = (
                text
                .replace(
                    "SPENDING TRENDS",
                    "SPENDING BY CATEGORY",
                )
                .replace(
                    "30 DAYS     VS 90D",
                    "30 DAYS       VS USUAL",
                )
            )

            left(
                printer,
                text,
            )

    # ==========================================
    # RUNWAY
    # ==========================================

    if monthly_spend > 0:

        printer.text("\n")

        for text in (
            runway_receipt_lines(
                float(debt_summary["net_liquid"]),
                savings_data,
                monthly_spend,
            )
        ):
            left(
                printer,
                text,
            )

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
        upcoming = [item for item in events
                    if today <= date.fromisoformat(item["date"]) <= end]
        change = sum((_decimal(item["amount"]) for item in upcoming), Decimal(0))
        printer.text("\n")
        left(printer, "NEXT 30 DAYS - LISTED EVENTS")
        print_line(printer)
        left(printer, _amount_line("KNOWN CASH CHANGE", change))
        left(printer, _amount_line("CASH AFTER EVENTS", _decimal(available_cash) + change))

    goals = finance_settings.get("savings_goals", [])
    if goals:
        printer.text("\n")
        left(printer, "SAVINGS GOALS")
        print_line(printer)
        for goal in goals:
            for row in _amount_rows(str(goal["name"]), goal["saved"]):
                left(printer, row)
            left(printer, _amount_line("  TARGET", goal["target"]))

    line(printer, "=")
