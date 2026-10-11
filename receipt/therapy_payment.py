"""Recognise a recent outgoing therapy payment before printing its reminder."""
import re
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def _words(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def recent_therapy_payment(transactions, *, payee="", today=None, days=2):
    today = today or datetime.now(ZoneInfo("Europe/London")).date()
    terms = tuple(dict.fromkeys(filter(None, (_words("therapy"), _words(payee)))))
    for transaction in transactions or ():
        if not isinstance(transaction, dict):
            continue
        raw_date = (transaction.get("timestamp") or transaction.get("transaction_date")
                    or transaction.get("date"))
        try:
            paid_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            paid_on = (paid_at.astimezone(ZoneInfo("Europe/London")).date()
                       if paid_at.tzinfo else paid_at.date())
            amount = float(transaction.get("amount", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(amount):
            continue
        if not today - timedelta(days=days) <= paid_on <= today:
            continue
        transaction_type = str(transaction.get("transaction_type", "")).upper()
        if transaction_type in {"CREDIT", "INCOME"} or (amount >= 0 and transaction_type != "DEBIT"):
            continue
        description = _words(" ".join(str(transaction.get(key) or "") for key in
                                      ("description", "merchant_name", "reference")))
        padded = f" {description} "
        if any(f" {term} " in padded for term in terms):
            return True
    return False
