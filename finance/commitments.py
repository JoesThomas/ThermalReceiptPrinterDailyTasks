"""Monthly debt repayments to show alongside recurring bills."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
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
            result.append({"name": name, "amount": amount, "category": "repayment",
                           "match": item.get("match", [])})
    return result


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
