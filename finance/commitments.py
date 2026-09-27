"""Monthly debt repayments to show alongside recurring bills."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta
import re


def _key(name):
    return re.sub(r"[^a-z0-9]+", "", str(name).casefold())


def _positive_amount(value):
    try:
        amount = Decimal(str(value))
        return float(amount) if amount.is_finite() and amount > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def repayment_commitments(subscriptions_data, settings):
    """Return repayments not already listed as monthly subscriptions.

    `monthly_commitment_name` links an instalment/debt to an existing monthly
    row when its display name differs. An unmatched payment has not been proven
    paid merely because it is included here.
    """
    monthly = subscriptions_data.get("monthly", [])
    known = {_key(item.get("name")) for item in monthly if isinstance(item, dict)}
    result = []
    sources = (
        subscriptions_data.get("instalments", []),
        settings.get("debts", []),
    )
    for source in sources:
        for item in source:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "Repayment")).strip()
            alias = str(item.get("monthly_commitment_name") or name)
            key = _key(alias)
            if not key or key in known:
                continue
            amount = _positive_amount(item.get("monthly_payment", item.get("amount")))
            if amount is None:
                continue
            balance = item.get("remaining_balance", item.get("balance"))
            if balance is not None and _positive_amount(balance) is None:
                continue
            if item.get("payments_remaining") == 0:
                continue
            known.add(key)
            match = item.get("match", [])
            # Amazon instalments have the same merchant as ordinary purchases;
            # the paid check also requires the precise monthly payment amount.
            if not match and "amazon" in _key(name):
                match = ["amazon.co.uk"]
            result.append({"name": name, "amount": amount, "category": "repayment",
                           "match": match})
    return result


def inferred_netflix_commitment(monthly, transactions, today):
    """Use a recent Netflix charge when no explicit monthly entry exists."""
    if any(isinstance(item, dict) and (
        "netflix" in _key(item.get("name"))
        or "netflix" in str(item.get("match", "")).casefold()
    ) for item in monthly):
        return None
    recent = []
    for tx in transactions:
        label = " ".join(str(tx.get(field) or "") for field in ("merchant_name", "description"))
        if "netflix" not in label.casefold():
            continue
        raw_date = tx.get("timestamp") or tx.get("transaction_date") or tx.get("date")
        try:
            paid_on = (raw_date if isinstance(raw_date, date) and not isinstance(raw_date, datetime)
                       else datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date())
            raw_amount = Decimal(str(tx.get("amount")))
        except (ValueError, TypeError, InvalidOperation):
            continue
        if not raw_amount.is_finite() or raw_amount == 0:
            continue
        if str(tx.get("transaction_type", "")).upper() in ("CREDIT", "REFUND"):
            continue
        if raw_amount > 0 and not str(tx.get("transaction_type", "")).upper() in ("DEBIT", "CARD_PAYMENT"):
            continue
        if today - timedelta(days=45) <= paid_on <= today:
            recent.append((paid_on, abs(raw_amount)))
    if not recent:
        return None
    amount = float(max(recent, key=lambda row: row[0])[1])
    return {"name": "Netflix", "amount": amount, "category": "subscription",
            "match": ["netflix"]}


def summarize_monthly_commitments(monthly):
    paid, due = [], []
    for item in monthly:
        amount = _positive_amount(item.get("amount"))
        if amount is None:
            continue
        row = {"name": str(item.get("name", "Subscription")),
               "amount": amount, "category": item.get("category", "")}
        (paid if item.get("paid") else due).append(row)
    return {
        "paid": paid,
        "due": due,
        "paid_total": sum(item["amount"] for item in paid),
        "due_bills": sum(item["amount"] for item in due
                         if item["category"] not in ("savings", "repayment")),
        "due_savings": sum(item["amount"] for item in due
                           if item["category"] == "savings"),
        "due_repayments": sum(item["amount"] for item in due
                              if item["category"] == "repayment"),
        "remaining_total": sum(item["amount"] for item in due),
    }
