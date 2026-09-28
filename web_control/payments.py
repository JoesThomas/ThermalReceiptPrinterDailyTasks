"""Group this month's bank debits without losing identical repeat purchases."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
import math
import re

from finance_trends import _parse_date, clean_spending_transactions


def external_payments(transactions):
    """Apply receipt exclusions, deduplicating true IDs while keeping idless repeats."""
    indexed = []
    for index, tx in enumerate(transactions or []):
        if not isinstance(tx, dict):
            continue
        item = dict(tx)
        if not item.get("transaction_id") and not item.get("id"):
            item["transaction_id"] = f"web-idless-{index}"
        indexed.append(item)
    return clean_spending_transactions(indexed)


def merchant_name(tx):
    raw = str(tx.get("merchant_name") or tx.get("merchant") or
              tx.get("spend_description") or tx.get("description") or "Unknown merchant").strip()
    name = re.sub(r"\s+", " ", raw)
    # Marketplace order suffixes vary for each purchase, but share a merchant.
    if re.search(r"(?:AMZNMKTPLACE|AMAZON\.CO\.UK)", name, re.I):
        return "Amazon"
    name = re.sub(r"\*[A-Z0-9]{7,}\b", "", name, flags=re.I).strip(" *")
    return name or "Unknown merchant"


def monthly_payments(transactions, today: date):
    grouped = defaultdict(list)
    names = {}
    for tx in external_payments(transactions):
        paid_on = _parse_date(tx)
        if paid_on is None or (paid_on.year, paid_on.month) != (today.year, today.month) or paid_on > today:
            continue
        amount = tx.get("spend_amount", 0)
        if not math.isfinite(amount) or amount <= 0:
            continue
        label = merchant_name(tx)
        key = label.casefold()
        names.setdefault(key, label)
        grouped[key].append({"date": paid_on, "amount": Decimal(str(amount)).quantize(Decimal("0.01")),
                             "description": str(tx.get("spend_description") or tx.get("description") or label)})
    merchants = []
    for key, records in grouped.items():
        records.sort(key=lambda item: item["date"], reverse=True)
        total = sum((item["amount"] for item in records), Decimal("0.00"))
        merchants.append({"name": names[key],
                          "amount": total, "count": len(records), "payments": records})
    merchants.sort(key=lambda item: (-item["amount"], item["name"].casefold()))
    total = sum((item["amount"] for item in merchants), Decimal("0.00"))
    return {"label": today.strftime("%B %Y"), "total": total,
            "count": sum(item["count"] for item in merchants), "merchants": merchants}
