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

    available_cash = (
        hsbc
        + monzo
        - amex
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

    net_cash = (
        available_cash
        + st["net_cash"]
    )

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

    # ==========================================
    # ACCOUNTS
    # ==========================================

    left(
        printer,
        "ACCOUNTS",
    )

    line(
        printer,
        "-",
    )

    left(
        printer,
        (
            f"{'HSBC CURRENT':<27}"
            f"{_money(hsbc):>15}"
        ),
    )

    left(
        printer,
        (
            f"{'MONZO':<27}"
            f"{_money(monzo):>15}"
        ),
    )

    left(
        printer,
        (
            f"{'AMEX':<27}"
            f"{_money(-amex):>15}"
        ),
    )

    # ==========================================
    # SAVINGS
    # ==========================================

    if st["accounts"]:

        for text in (
            savings_receipt_lines(
                savings_data
            )
        ):
            left(
                printer,
                text,
            )

    line(
        printer,
        "-",
    )

    left(
        printer,
        (
            f"{'NET CASH':<27}"
            f"{_money(net_cash):>15}"
        ),
    )

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

            left(
                printer,
                (
                    f"{name:<27}"
                    f"{_money(value):>15}"
                ),
            )

        line(
            printer,
            "-",
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

        gain_pct = (
            investment_summary[
                "gain_pct"
            ]
        )

        if gain_pct is not None:

            left(
                printer,
                (
                    f"{'RETURN':<27}"
                    f"{gain_pct:>+14.1f}%"
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

    left(
        printer,
        (
            f"EVERYDAY SPEND"
            f"{_money(last30):>20}"
        ),
    )

    left(
        printer,
        (
            f"FIXED COMMITMENTS"
            f"{_money(fixed_commitments):>17}"
        ),
    )

    left(
        printer,
        (
            f"TOTAL OUTGOINGS"
            f"{_money(total_outgoings):>19}"
        ),
    )

    print_line(
        printer,
        "-",
    )

    left(
        printer,
        (
            f"3 MONTH AVG"
            f"{_money(usual):>23}"
        ),
    )

    if usual > 0:
        change_pct = (
                (last30 - usual)
                / usual
                * 100.0
        )

        left(
            printer,
            (
                f"CHANGE"
                f"{change_pct:>27.1f}%"
            ),
        )

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
                available_cash,
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

    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

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

    # ==========================================
    # SUMMARY
    # ==========================================

    line(
        printer,
        "=",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        "SUMMARY",
    )

    printer.set(
        bold=False
    )

    line(
        printer,
        "-",
    )

    left(
        printer,
        (
            f"{'NET CASH':<27}"
            f"{_money(net_cash):>15}"
        ),
    )

    if overall_change is not None:

        left(
            printer,
            (
                f"{'SPENDING CHANGE':<27}"
                f"{overall_change:>+14.1f}%"
            ),
        )

    line(
        printer,
        "=",
    )