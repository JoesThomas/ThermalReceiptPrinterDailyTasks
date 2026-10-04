"""Group this month's bank debits without losing identical repeat purchases."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import hashlib
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


def payment_identity(on,merchant,amount):
    return hashlib.sha256(f'{on}|{merchant.strip()[:160]}|{round(float(amount),2)}'.encode()).hexdigest()


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
                             "review_id":payment_identity(paid_on,str(tx.get("merchant_name") or tx.get("merchant") or tx.get("description") or "").strip(),amount),
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


def incoming_review(salary, other, today: date):
    """Summarise classified bank credits without inventing missing history."""
    start = today - timedelta(days=29)
    recent = []
    for category, items in (("Salary", salary), (None, other)):
        for item in items:
            paid_on = item.get("date")
            if not isinstance(paid_on, date) or not start <= paid_on <= today:
                continue
            try:
                amount = Decimal(str(item["amount"])).quantize(Decimal("0.01"))
            except (KeyError, ValueError, ArithmeticError):
                continue
            if not amount.is_finite() or amount <= 0:
                continue
            recent.append({"date": paid_on, "amount": amount,
                           "name": str(item.get("name") or "Incoming payment"),
                           "category": category or str(item.get("category") or "OTHER IN").title()})
    recent.sort(key=lambda item: (item["date"], item["name"]), reverse=True)
    grouped = defaultdict(list)
    for item in recent:
        grouped[item["category"]].append(item)
    categories = [{"name": name, "count": len(items),
                   "amount": sum((item["amount"] for item in items), Decimal("0.00")),
                   "payments": items}
                  for name, items in grouped.items()]
    categories.sort(key=lambda item: (-item["amount"], item["name"]))
    maximum = max((item["amount"] for item in categories), default=Decimal("0.00"))
    for item in categories:
        item["percent"] = round(100 * float(item["amount"] / maximum), 1) if maximum else 0
    month = [item for item in recent if (item["date"].year, item["date"].month)
             == (today.year, today.month)]
    return {"recent": recent, "categories": categories,
            "total": sum((item["amount"] for item in recent), Decimal("0.00")),
            "month_total": sum((item["amount"] for item in month), Decimal("0.00")),
            "month_count": len(month)}


def cash_flow_review(income, payments, today: date):
    """Compare known incoming and outgoing transactions across four weeks."""
    start = today - timedelta(days=27)
    income_weeks = [Decimal("0.00") for _ in range(4)]
    outgoing_weeks = [Decimal("0.00") for _ in range(4)]
    for item in income["recent"]:
        if item["date"] >= start:
            income_weeks[(item["date"] - start).days // 7] += item["amount"]
    outgoing_total = Decimal("0.00")
    for tx in payments:
        paid_on = _parse_date(tx)
        if paid_on is None or not today - timedelta(days=29) <= paid_on <= today:
            continue
        try:
            amount = Decimal(str(tx["spend_amount"])).quantize(Decimal("0.01"))
        except (KeyError, ValueError, ArithmeticError):
            continue
        if not amount.is_finite() or amount <= 0:
            continue
        outgoing_total += amount
        if paid_on >= start:
            outgoing_weeks[(paid_on - start).days // 7] += amount
    maximum = max(income_weeks + outgoing_weeks, default=Decimal("0.00"))
    weeks = []
    for index in range(4):
        first = start + timedelta(days=index * 7)
        last = first + timedelta(days=6)
        weeks.append({"label": f"{first:%d %b}–{last:%d %b}",
                      "income": income_weeks[index], "outgoing": outgoing_weeks[index],
                      "income_percent": round(100 * float(income_weeks[index] / maximum), 1) if maximum else 0,
                      "outgoing_percent": round(100 * float(outgoing_weeks[index] / maximum), 1) if maximum else 0})
    return {"income": income["total"], "outgoing": outgoing_total,
            "net": income["total"] - outgoing_total, "weeks": weeks}
