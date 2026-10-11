"""Small, accessible finance chart summaries built from receipt inputs."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math
from pathlib import Path

from finance.commitments import summarize_monthly_commitments
from finance_trends import (EXCLUDED_CATEGORIES, _amount, _parse_date,
                            categorise_transaction, clean_spending_transactions, load_rules)

RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "finance_categories.json"


def finance_charts(transactions, commitments, today, rules=None):
    """Return numbers and bounded percentages for three finance visuals."""
    summary = summarize_monthly_commitments(commitments)
    paid = round(summary["paid_total"], 2)
    due = round(summary["remaining_total"], 2)
    total_commitments = paid + due
    commitments_chart = {
        "paid": paid,
        "due": due,
        "total": round(total_commitments, 2),
        "paid_percent": round(100 * paid / total_commitments, 1) if total_commitments else 0,
        "due_percent": round(100 * due / total_commitments, 1) if total_commitments else 0,
    }

    rules = load_rules(RULES_FILE) if rules is None else rules
    category_totals = defaultdict(float)
    week_totals = [0.0] * 4
    start = today - timedelta(days=27)
    category_start = today - timedelta(days=29)
    for tx in clean_spending_transactions(transactions):
        paid_on = _parse_date(tx)
        if paid_on is None or not category_start <= paid_on <= today:
            continue
        category = categorise_transaction(tx, rules)
        if category in EXCLUDED_CATEGORIES:
            continue
        amount = _amount(tx)
        if not math.isfinite(amount) or amount <= 0:
            continue
        category_totals[category] += amount
        if paid_on >= start:
            week_totals[(paid_on - start).days // 7] += amount

    # All category bars are shown: no invisible 'other' total.
    categories = [{"name": name, "amount": round(amount, 2)}
                  for name, amount in sorted(category_totals.items(),
                                             key=lambda row: (-row[1], row[0]))]
    max_category = max((item["amount"] for item in categories), default=0)
    for item in categories:
        item["percent"] = round(100 * item["amount"] / max_category, 1) if max_category else 0

    max_week = max(week_totals, default=0)
    weeks = []
    for index, amount in enumerate(week_totals):
        first = start + timedelta(days=7 * index)
        last = first + timedelta(days=6)
        weeks.append({"label": f"{first:%d %b}–{last:%d %b}",
                      "amount": round(amount, 2),
                      "percent": round(100 * amount / max_week, 1) if max_week else 0})
    return {"commitments": commitments_chart, "categories": categories,
            "weeks": weeks, "weekly_total": round(sum(week_totals), 2),
            "spending_total": round(sum(category_totals.values()), 2)}


def instalment_progress(item):
    """Calculate an instalment progress bar only when a reliable balance exists."""
    try:
        remaining = float(item.get("remaining_balance"))
        original = item.get("total_price")
        if original is None:
            paid = float(item.get("paid_to_date"))
            original = paid + remaining
        original = float(original)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(original) and math.isfinite(remaining)
            and 0 <= remaining <= original and original > 0):
        return None
    return {"paid": round(original - remaining, 2),
            "remaining": round(remaining, 2),
            "total": round(original, 2),
            "percent": round(100 * (original - remaining) / original, 1)}
