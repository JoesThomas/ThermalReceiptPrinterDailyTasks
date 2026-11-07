from __future__ import annotations

import json

from pathlib import Path
from finance.yearly_subscriptions import annual_subscription_rows
from finance.bill_payments import monthly_contract_ended, monthly_matches
from finance.commitments import repayment_commitments
from finance.money import parse
from receipt.local_time import uk_today


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

SUBSCRIPTIONS_FILE = (
    PROJECT_ROOT
    / "data"
    / "subscriptions.json"
)

def load_subscriptions():
    if not SUBSCRIPTIONS_FILE.exists():
        return {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        }
    with SUBSCRIPTIONS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)
    data.setdefault(
        "monthly",
        [],
    )
    data.setdefault(
        "yearly",
        [],
    )
    data.setdefault(
        "instalments",
        [],
    )
    return data

def save_subscriptions(data):
    from storage import write_json
    write_json(SUBSCRIPTIONS_FILE, data)


def update_subscriptions_from_transactions(transactions, *, today=None, finance_settings=None):
    """Save newly matched bill payments and report changes to their estimates."""
    today = today or uk_today()
    data = load_subscriptions()
    monthly = [item for item in data["monthly"] if not monthly_contract_ended(item, today)]
    yearly = data["yearly"]
    repayments = repayment_commitments(data, finance_settings or {})
    annual = annual_subscription_rows(yearly, transactions, today)
    reserved = {row["bank_match_index"] for row in annual if row["bank_match_index"] is not None}
    matches = monthly_matches(monthly + repayments, transactions, today, reserved=reserved)
    observations = [
        (monthly[index], "monthly", paid_on, float(amount))
        for index, (_, paid_on, amount) in matches.items() if index < len(monthly)
    ]
    observations.extend(
        (yearly[row["subscription_index"]], "yearly", row["bank_paid_date"], row["bank_paid_amount"])
        for row in annual if row["bank_paid_date"] is not None
    )

    changes = []
    changed = False
    for item, frequency, paid_on, amount in observations:
        paid_date = paid_on.isoformat()
        if (item.get("last_paid") or "") >= paid_date:
            continue
        item["last_paid"] = paid_date
        history = item.setdefault("history", [])
        item["history"] = (history + [{"date": paid_date, "amount": amount}])[-24:]
        expected = parse(item.get("amount"))
        item["amount"] = amount
        changed = True
        if expected is None or parse(amount) == expected:
            continue
        previous = float(expected)
        difference = round(amount - previous, 2)
        changes.append({
            "name": item.get("name", "Subscription"),
            "frequency": frequency,
            "date": paid_date,
            "old_amount": previous,
            "new_amount": amount,
            "difference": difference,
            "percentage": difference / previous * 100 if previous else 0.0,
        })

    if changed:
        save_subscriptions(data)
    return changes
