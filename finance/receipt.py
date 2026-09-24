from __future__ import annotations
from finance.investments import (
    load_investments,
    investment_totals,
    investment_age_days,
    investment_snapshot,
)
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime

from finance_trends import (
    load_rules, category_trends, receipt_trend_lines,
    clean_spending_transactions, spending_total, usual_30_day_spend,
    debug_spending_transactions,
    completed_periods_to_save, period_analysis, save_snapshot,
    load_snapshot, add_savings_growth_to_analysis,
    savings_growth_receipt_lines, period_receipt_lines,
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

def _payment_date(item):
    for key in ("next_date", "date", "payment_date", "due_date"):
        value = item.get(key)
        if value:
            if hasattr(value, "strftime"):
                return value.strftime("%d %b").upper()
            text = str(value)
            try:
                return datetime.fromisoformat(text.replace("Z","+00:00")).strftime("%d %b").upper()
            except Exception:
                return text[:10].upper()
    return ""

def print_integrated_finance(
    printer, left, line, balances, transactions,
    direct_debits=None, standing_orders=None, subscriptions=None,
    spending_summary=None,
):
    direct_debits = direct_debits or []
    standing_orders = standing_orders or []
    subscriptions = subscriptions or []
    spending_summary = spending_summary or {}
    transactions = transactions or []

    hsbc = float(balances.get("HSBC", {}).get("available", 0) or 0)
    monzo = float(balances.get("MONZO", {}).get("available", 0) or 0)
    amex = float(balances.get("AMEX", {}).get("current", 0) or 0)
    available_cash = hsbc + monzo - amex

    savings_data = load_savings(SAVINGS_FILE)
    st = savings_totals(savings_data)
    net_cash = available_cash + st["net_cash"]

    investment_data = load_investments(
        INVESTMENTS_FILE
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

    # Use one cleaned transaction set for the headline total, category trends
    # and baseline. This prevents transfers, savings movements, repayments and
    # duplicates from inflating LAST 30 DAYS.
    clean_transactions = clean_spending_transactions(transactions)
    last30 = spending_total(clean_transactions, days=30)
    usual = usual_30_day_spend(clean_transactions)
    monthly_spend = usual or last30
    overall_change = ((last30 - usual) / usual * 100) if usual > 0 else None

    if DEBUG_SPENDING:
        debug_spending_transactions(clean_transactions, days=30)

    line(printer, "="); left(printer, "FINANCE"); line(printer, "=")
    left(printer, "ACCOUNTS"); line(printer, "-")
    left(printer, f"{'HSBC CURRENT':<27}{_money(hsbc):>15}")
    left(printer, f"{'MONZO':<27}{_money(monzo):>15}")
    left(printer, f"{'AMEX':<27}{_money(-amex):>15}")

    if st["accounts"]:
        line(
            printer,
            "-",
        )

        for x in savings_receipt_lines(
                savings_data
        ):
            left(
                printer,
                x,
            )

    line(
        printer,
        "-",
    )

    left(
        printer,
        "NET CASH",
    )

    left(
        printer,
        f"{'':<27}{_money(net_cash):>15}",
    )

    # ------------------------------------------
    # INVESTMENTS
    # ------------------------------------------

    if investment_data["accounts"]:
        line(
            printer,
            "-",
        )

        left(
            printer,
            "INVESTMENTS",
        )

        line(
            printer,
            "-",
        )

        for account in investment_data[
            "accounts"
        ]:
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

            left(
                printer,
                (
                    f"{name:<27}"
                    f"{_money(value):>15}"
                ),
            )

        left(
            printer,
            (
                f"{'TOTAL':<27}"
                f"{_money(investment_summary['value']):>15}"
            ),
        )

        left(
            printer,
            (
                f"{'CONTRIBUTED':<27}"
                f"{_money(investment_summary['contributions']):>15}"
            ),
        )

        left(
            printer,
            (
                f"{'GAIN / LOSS':<27}"
                f"{_money(investment_summary['gain']):>15}"
            ),
        )

        if (
                investment_summary[
                    "gain_pct"
                ]
                is not None
        ):
            left(
                printer,
                (
                    f"{'RETURN':<27}"
                    f"{investment_summary['gain_pct']:>+14.1f}%"
                ),
            )

        if (
                investment_age is not None
                and investment_age > 30
        ):
            left(
                printer,
                (
                    f"VALUE {investment_age} "
                    f"DAYS OLD"
                ),
            )

    payments = []
    for item in direct_debits + standing_orders + subscriptions:
        name = str(item.get("name") or item.get("description") or "PAYMENT").upper()[:18]
        try: amount = abs(float(item.get("amount", 0) or 0))
        except Exception: amount = 0
        payments.append((name, amount, _payment_date(item)))
    if payments:
        line(printer, "-"); left(printer, "UPCOMING PAYMENTS"); line(printer, "-")
        left(printer, f"{'NAME':<18}{'AMOUNT':>12}{'DATE':>12}")
        for name, amount, due in payments[:12]:
            left(printer, f"{name:<18}{_money(amount):>12}{due:>12}")

    line(printer, "-"); left(printer, "SPENDING"); line(printer, "-")
    left(printer, f"{'LAST 30 DAYS':<27}{_money(last30):>15}")
    left(printer, f"{'USUAL 30 DAYS':<27}{_money(usual):>15}")
    if overall_change is not None:
        left(printer, f"{'CHANGE':<27}{overall_change:>+14.1f}%")

    rules = load_rules(RULES_FILE)
    trends = category_trends(clean_transactions, rules, minimum_current_spend=20.0)
    if trends:
        line(printer, "-")
        for x in receipt_trend_lines(trends):
            # Skip duplicated largest-changes block on the everyday receipt.
            if x == "LARGEST CHANGES":
                break
            left(printer, x.replace("SPENDING TRENDS", "SPENDING BY CATEGORY")
                           .replace("30 DAYS     VS 90D", "30 DAYS       VS USUAL"))

    if monthly_spend > 0:
        line(printer, "-")
        for x in runway_receipt_lines(available_cash, savings_data, monthly_spend):
            left(printer, x)

    # -------------------------------------------------
    # QUARTERLY / YEARLY ANALYSIS
    # -------------------------------------------------
    #
    # Only runs when a quarter/year has just completed.
    #

    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    for kind, period_date in completed_periods_to_save(
            today
    ):
        analysis = period_analysis(
            clean_transactions,
            rules,
            kind,
            period_date,
        )

        # ---------------------------------------------
        # SAVINGS SNAPSHOT
        # ---------------------------------------------

        current_savings = savings_snapshot(
            savings_data
        )

        prev_label = previous_period_label(
            kind,
            analysis["label"],
        )

        previous = load_snapshot(
            HISTORY_FILE,
            prev_label,
        )

        analysis = add_savings_growth_to_analysis(
            analysis,
            current_savings,
            previous,
        )

        # ---------------------------------------------
        # INVESTMENT SNAPSHOT
        # ---------------------------------------------

        current_investments = investment_snapshot(
            investment_data
        )

        # ---------------------------------------------
        # SAVE COMPLETE PERIOD SNAPSHOT
        # ---------------------------------------------

        save_snapshot(
            HISTORY_FILE,
            analysis,
            investment_snapshot=current_investments,
        )

        # ---------------------------------------------
        # PRINT PERIOD ANALYSIS
        # ---------------------------------------------

        line(
            printer,
            "=",
        )

        for x in period_receipt_lines(
                analysis
        ):
            left(
                printer,
                x,
            )

        for x in savings_growth_receipt_lines(
                analysis
        ):
            left(
                printer,
                x,
            )

    line(printer, "="); left(printer, "SUMMARY"); line(printer, "-")
    left(printer, f"{'NET CASH':<27}{_money(net_cash):>15}")
    if overall_change is not None:
        left(printer, f"{'SPENDING CHANGE':<27}{overall_change:>+14.1f}%")
