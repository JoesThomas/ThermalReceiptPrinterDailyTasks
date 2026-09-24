from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import calendar
import json
import math
import re

from finance.investments import (
    load_investments,
    investment_snapshot,
)

DEFAULT_CATEGORIES = [
    "FOOD",
    "EATING OUT",
    "TRANSPORT",
    "ENTERTAINMENT",
    "SHOPPING",
    "HOUSEHOLD",
    "BILLS & UTILITIES",
    "SUBSCRIPTIONS",
    "HEALTH",
    "TRAVEL",
    "CASH",
    "OTHER",
]

EXCLUDED_CATEGORIES = {"TRANSFER", "SAVINGS", "CREDIT CARD PAYMENT", "INCOME"}

def _normalise_merchant(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 &'-]", " ", (value or "").upper())).strip()

def load_rules(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def categorise_transaction(tx: dict, rules: dict) -> str:
    explicit = str(tx.get("category") or tx.get("transaction_category") or "").upper().strip()
    merchant = _normalise_merchant(
        str(tx.get("merchant_name") or tx.get("merchant") or tx.get("description") or "")
    )

    for needle, category in rules.items():
        if _normalise_merchant(needle) in merchant:
            return str(category).upper().strip()

    aliases = {
        "GROCERIES": "FOOD",
        "FOOD_AND_DRINK": "EATING OUT",
        "RESTAURANTS": "EATING OUT",
        "TRANSPORTATION": "TRANSPORT",
        "TRAVEL": "TRAVEL",
        "ENTERTAINMENT": "ENTERTAINMENT",
        "SHOPPING": "SHOPPING",
        "BILLS": "BILLS & UTILITIES",
        "UTILITIES": "BILLS & UTILITIES",
        "HEALTH": "HEALTH",
        "CASH": "CASH",
    }
    return aliases.get(explicit, explicit if explicit in DEFAULT_CATEGORIES else "OTHER")

def _parse_date(tx: dict) -> date | None:
    raw = tx.get("date") or tx.get("timestamp") or tx.get("transaction_date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(str(raw)[:10])
        except Exception:
            return None

def _amount(tx: dict) -> float:
    value = tx.get("amount", 0)
    if isinstance(value, dict):
        value = value.get("amount", 0)
    try:
        amount = float(value)
    except Exception:
        return 0.0
    # Spending is stored as positive magnitude regardless of provider sign convention.
    return abs(amount)

def _is_spend(tx: dict, category: str) -> bool:
    if category in EXCLUDED_CATEGORIES:
        return False
    tx_type = str(tx.get("type") or tx.get("transaction_type") or "").upper()
    description = _normalise_merchant(str(tx.get("description") or tx.get("merchant_name") or ""))
    exclusions = ("TRANSFER", "INTERNAL TRANSFER", "CREDIT CARD PAYMENT", "SAVINGS")
    if any(x in description for x in exclusions):
        return False
    if tx_type in {"CREDIT", "INCOME"} and not tx.get("is_refund"):
        return False
    return True



def _transaction_description(tx: dict) -> str:
    return str(
        tx.get("description")
        or tx.get("merchant_name")
        or tx.get("merchant")
        or tx.get("transaction_description")
        or ""
    ).strip()


def clean_spending_transactions(transactions: list[dict]) -> list[dict]:
    """
    Return one canonical list of genuine spending transactions.

    Excludes incoming money, refunds/reversals, internal transfers, savings
    movements, credit-card repayments and obvious duplicates.  Each returned
    item includes spend_amount, spend_date and spend_description while retaining
    the original provider fields used by the category analyser.
    """
    cleaned = []
    seen = set()

    exclusion_terms = (
        "INTERNAL TRANSFER",
        "TRANSFER BETWEEN",
        "TRANSFER TO",
        "TRANSFER FROM",
        "SAVINGS TRANSFER",
        "MOVE TO SAVINGS",
        "CREDIT CARD PAYMENT",
        "CARD REPAYMENT",
        "AMEX PAYMENT",
        "AMERICAN EXPRESS PAYMENT",
        "PAYMENT RECEIVED",
    )
    refund_terms = ("REFUND", "REVERSAL", "REVERSED")

    for tx in transactions or []:
        if not isinstance(tx, dict):
            continue

        raw_amount = tx.get("amount", 0)
        if isinstance(raw_amount, dict):
            raw_amount = raw_amount.get("amount", 0)
        try:
            amount = float(raw_amount or 0)
        except (TypeError, ValueError):
            continue

        tx_type = str(
            tx.get("type") or tx.get("transaction_type") or ""
        ).upper()
        description = _transaction_description(tx)
        description_upper = _normalise_merchant(description)

        # TrueLayer commonly marks outgoing transactions as DEBIT.  For sources
        # using signed values, a negative amount is also treated as outgoing.
        if amount >= 0 and tx_type not in {"DEBIT", "CARD_PAYMENT"}:
            continue

        if tx.get("is_refund"):
            continue
        if any(term in description_upper for term in refund_terms):
            continue
        if any(term in description_upper for term in exclusion_terms):
            continue

        category = str(
            tx.get("category") or tx.get("transaction_category") or ""
        ).upper().strip()
        if category in EXCLUDED_CATEGORIES:
            continue

        tx_date = _parse_date(tx)
        if tx_date is None:
            continue

        spend_amount = abs(amount)
        transaction_id = tx.get("transaction_id") or tx.get("id")
        provider = str(tx.get("provider") or tx.get("bank") or "").upper()

        if transaction_id:
            duplicate_key = ("ID", provider, str(transaction_id))
        else:
            duplicate_key = (
                "FALLBACK",
                provider,
                tx_date.isoformat(),
                round(spend_amount, 2),
                description_upper,
            )

        if duplicate_key in seen:
            continue
        seen.add(duplicate_key)

        item = dict(tx)
        item["spend_amount"] = spend_amount
        item["spend_date"] = tx_date.isoformat()
        item["spend_description"] = description
        cleaned.append(item)

    return cleaned


def spending_total(
    transactions: list[dict],
    days: int = 30,
    as_of: date | None = None,
) -> float:
    """Total cleaned spending in an inclusive N-day window."""
    if days <= 0:
        return 0.0
    as_of = as_of or date.today()
    start = as_of - timedelta(days=days - 1)
    total = 0.0
    for tx in transactions or []:
        d = _parse_date(tx)
        if d is None or not (start <= d <= as_of):
            continue
        try:
            total += float(tx.get("spend_amount", _amount(tx)) or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def usual_30_day_spend(
    transactions: list[dict],
    as_of: date | None = None,
    baseline_days: int = 90,
) -> float:
    """
    Return a 30-day equivalent based on the period immediately before the
    current 30-day window.  With the default 90-day baseline this is the
    preceding 90 days divided by three.
    """
    if baseline_days <= 0:
        return 0.0
    as_of = as_of or date.today()
    current_start = as_of - timedelta(days=29)
    baseline_end = current_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)

    total = 0.0
    for tx in transactions or []:
        d = _parse_date(tx)
        if d is None or not (baseline_start <= d <= baseline_end):
            continue
        try:
            total += float(tx.get("spend_amount", _amount(tx)) or 0)
        except (TypeError, ValueError):
            continue

    return round(total * (30.0 / baseline_days), 2)


def debug_spending_transactions(
    transactions: list[dict],
    days: int = 30,
    as_of: date | None = None,
) -> None:
    """Print the transactions behind the headline spend total to the console."""
    if days <= 0:
        return
    as_of = as_of or date.today()
    start = as_of - timedelta(days=days - 1)
    rows = []
    for tx in transactions or []:
        d = _parse_date(tx)
        if d is None or not (start <= d <= as_of):
            continue
        try:
            amount = float(tx.get("spend_amount", _amount(tx)) or 0)
        except (TypeError, ValueError):
            continue
        rows.append((d, amount, tx.get("spend_description") or _transaction_description(tx)))

    rows.sort(key=lambda row: row[0])
    print("\n" + "=" * 60)
    print("SPENDING DEBUG - LAST 30 DAYS")
    print("=" * 60)
    total = 0.0
    for d, amount, description in rows:
        total += amount
        print(f"{d.isoformat()} £{amount:>9.2f} {description}")
    print("-" * 60)
    print(f"TOTAL: £{total:.2f}")
    print("=" * 60 + "\n")

def _window_totals(
    transactions: list[dict],
    rules: dict,
    start: date,
    end: date,
) -> dict[str, float]:
    totals = defaultdict(float)

    for tx in transactions:
        d = _parse_date(tx)

        if d is None or not (start <= d <= end):
            continue

        category = categorise_transaction(
            tx,
            rules,
        )

        amount = float(
            tx.get(
                "spend_amount",
                _amount(tx),
            )
            or 0
        )

        totals[category] += amount

    return dict(totals)

def category_trends(
    transactions: list[dict],
    rules: dict,
    as_of: date | None = None,
    current_days: int = 30,
    baseline_days: int = 90,
    minimum_current_spend: float = 20.0,
) -> list[dict]:
    as_of = as_of or date.today()
    current_start = as_of - timedelta(days=current_days - 1)
    baseline_end = current_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)

    current = _window_totals(transactions, rules, current_start, as_of)
    baseline = _window_totals(transactions, rules, baseline_start, baseline_end)

    results = []
    categories = sorted(set(current) | set(baseline))
    for category in categories:
        current_value = current.get(category, 0.0)
        baseline_total = baseline.get(category, 0.0)
        baseline_equivalent = baseline_total * (current_days / baseline_days)

        if current_value < minimum_current_spend and baseline_equivalent < minimum_current_spend:
            continue

        if baseline_equivalent > 0.01:
            pct = ((current_value - baseline_equivalent) / baseline_equivalent) * 100.0
        else:
            pct = None

        results.append({
            "category": category,
            "current": round(current_value, 2),
            "baseline_30d": round(baseline_equivalent, 2),
            "change_amount": round(current_value - baseline_equivalent, 2),
            "change_pct": round(pct, 1) if pct is not None else None,
        })

    return sorted(results, key=lambda x: x["current"], reverse=True)

def largest_changes(trends: list[dict], count: int = 2) -> list[dict]:
    eligible = [x for x in trends if x["change_pct"] is not None]
    return sorted(eligible, key=lambda x: abs(x["change_amount"]), reverse=True)[:count]

def _period_bounds(kind: str, d: date) -> tuple[date, date, str]:
    if kind == "quarter":
        q = ((d.month - 1) // 3) + 1
        start_month = (q - 1) * 3 + 1
        start = date(d.year, start_month, 1)
        end_month = start_month + 2
        end = date(d.year, end_month, calendar.monthrange(d.year, end_month)[1])
        return start, end, f"{d.year}-Q{q}"
    if kind == "year":
        return date(d.year, 1, 1), date(d.year, 12, 31), str(d.year)
    raise ValueError(kind)

def previous_period(kind: str, start: date) -> tuple[date, date]:
    if kind == "quarter":
        previous_day = start - timedelta(days=1)
        pstart, pend, _ = _period_bounds("quarter", previous_day)
        return pstart, pend
    return date(start.year - 1, 1, 1), date(start.year - 1, 12, 31)

def period_analysis(transactions: list[dict], rules: dict, kind: str, period_date: date) -> dict:
    start, end, label = _period_bounds(kind, period_date)
    pstart, pend = previous_period(kind, start)
    current = _window_totals(transactions, rules, start, end)
    previous = _window_totals(transactions, rules, pstart, pend)

    total = sum(current.values())
    previous_total = sum(previous.values())
    change = total - previous_total
    pct = (change / previous_total * 100.0) if previous_total > 0.01 else None

    rows = []
    for category in sorted(set(current) | set(previous)):
        now = current.get(category, 0.0)
        before = previous.get(category, 0.0)
        delta = now - before
        cpct = (delta / before * 100.0) if before > 0.01 else None
        rows.append({
            "category": category,
            "amount": round(now, 2),
            "previous": round(before, 2),
            "change_amount": round(delta, 2),
            "change_pct": round(cpct, 1) if cpct is not None else None,
            "share_pct": round(now / total * 100.0, 1) if total else 0.0,
        })

    rows.sort(key=lambda x: x["amount"], reverse=True)
    return {
        "kind": kind,
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_spend": round(total, 2),
        "previous_total": round(previous_total, 2),
        "change_amount": round(change, 2),
        "change_pct": round(pct, 1) if pct is not None else None,
        "categories": rows,
        "largest_changes": sorted(
            [r for r in rows if r["change_pct"] is not None],
            key=lambda r: abs(r["change_amount"]),
            reverse=True,
        )[:3],
    }

def save_snapshot(
    history_path: Path,
    analysis: dict,
    savings_snapshot: dict | None = None,
    investment_snapshot: dict | None = None,
) -> None:
    if savings_snapshot:
        analysis = dict(analysis)
        analysis["savings"] = savings_snapshot
    if investment_snapshot:
        analysis = dict(analysis)
        analysis["investments"] = (
            investment_snapshot
        )
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
    except Exception:
        history = {}
    if not isinstance(history, dict):
        history = {}
    history[analysis["label"]] = analysis
    tmp = history_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2), encoding="utf-8")
    tmp.replace(history_path)

def load_snapshot(history_path: Path, label: str) -> dict | None:
    if not history_path.exists():
        return None
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data.get(label) if isinstance(data, dict) else None
    except Exception:
        return None

def completed_periods_to_save(as_of: date) -> list[tuple[str, date]]:
    result = []
    # On the first day of a new quarter, save the quarter that just ended.
    if as_of.day == 1 and as_of.month in {1, 4, 7, 10}:
        result.append(("quarter", as_of - timedelta(days=1)))
    # On 1 January also save the year that just ended.
    if as_of.month == 1 and as_of.day == 1:
        result.append(("year", date(as_of.year - 1, 12, 31)))
    return result

def format_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}£{abs(value):,.2f}"

def format_trend(value: float | None) -> str:
    if value is None:
        return "NEW"
    return f"{value:+.1f}%"

def receipt_trend_lines(trends: list[dict], max_categories: int = 8) -> list[str]:
    lines = ["SPENDING TRENDS", "-" * 42, "                    30 DAYS     VS 90D"]
    for row in trends[:max_categories]:
        name = row["category"][:18]
        amount = format_money(row["current"])
        trend = format_trend(row["change_pct"])
        lines.append(f"{name:<18}{amount:>12}{trend:>12}")
    changes = largest_changes(trends, 2)
    if changes:
        lines += ["", "LARGEST CHANGES", "-" * 42]
        for row in changes:
            lines.append(
                f"{row['category'][:18]:<18}"
                f"{format_money(row['change_amount']):>12}"
                f"{format_trend(row['change_pct']):>12}"
            )
    return lines

def period_receipt_lines(analysis: dict) -> list[str]:
    heading = "QUARTERLY ANALYSIS" if analysis["kind"] == "quarter" else "YEARLY ANALYSIS"
    lines = [
        heading,
        "-" * 42,
        analysis["label"],
        f"TOTAL SPEND            {format_money(analysis['total_spend']):>14}",
    ]
    if analysis["change_pct"] is not None:
        lines.append(
            f"VS PREVIOUS PERIOD     {format_trend(analysis['change_pct']):>14}"
        )
    lines += ["", "BY CATEGORY", "-" * 42]
    for row in analysis["categories"][:10]:
        lines.append(
            f"{row['category'][:18]:<18}"
            f"{format_money(row['amount']):>12}"
            f"{format_trend(row['change_pct']):>12}"
        )
    if analysis["largest_changes"]:
        lines += ["", "LARGEST CHANGES", "-" * 42]
        for row in analysis["largest_changes"]:
            lines.append(
                f"{row['category'][:18]:<18}"
                f"{format_money(row['change_amount']):>12}"
                f"{format_trend(row['change_pct']):>12}"
            )
    return lines


def savings_growth(current_snapshot: dict, previous_snapshot: dict | None) -> dict | None:
    """Compare total savings with a previously saved period snapshot."""
    if not previous_snapshot:
        return None
    previous_savings = previous_snapshot.get("savings") or {}
    try:
        current_total = float(current_snapshot.get("savings_total", 0))
        previous_total = float(previous_savings.get("savings_total", 0))
    except (TypeError, ValueError):
        return None
    change = current_total - previous_total
    pct = (change / previous_total * 100.0) if previous_total > 0.01 else None
    return {
        "start": round(previous_total, 2),
        "end": round(current_total, 2),
        "change": round(change, 2),
        "change_pct": round(pct, 1) if pct is not None else None,
    }


def add_savings_growth_to_analysis(analysis, current_savings_snapshot, previous_analysis):
    result = dict(analysis)
    result["savings"] = current_savings_snapshot
    growth = savings_growth(current_savings_snapshot, previous_analysis)
    if growth:
        result["savings_growth"] = growth
    return result


def savings_growth_receipt_lines(analysis: dict) -> list[str]:
    growth = analysis.get("savings_growth")
    if not growth:
        return []
    lines = [
        "SAVINGS CHANGE",
        "-" * 42,
        f"{'START OF PERIOD':<27}{format_money(growth['start']):>15}",
        f"{'END OF PERIOD':<27}{format_money(growth['end']):>15}",
        f"{'CHANGE':<27}{format_money(growth['change']):>15}",
    ]
    if growth.get("change_pct") is not None:
        lines.append(f"{'PERCENT CHANGE':<27}{format_trend(growth['change_pct']):>15}")
    return lines
