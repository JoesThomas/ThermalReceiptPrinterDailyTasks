from __future__ import annotations

import json
import math

from datetime import datetime
from pathlib import Path
from finance.yearly_subscriptions import annual_subscription_rows
from zoneinfo import ZoneInfo


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


def _description(transaction):
    return str(
        transaction.get(
            "description",
            "",
        )
        or transaction.get(
            "spend_description",
            "",
        )
        or ""
    ).upper()


def _amount(transaction):
    try:
        value = abs(float(transaction.get('amount', 0)))
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _is_debit(transaction):
    kind = str(transaction.get('transaction_type') or transaction.get('type') or '').upper()
    if kind in {'CREDIT', 'INCOME', 'REFUND'}:
        return False
    try:
        value = float(transaction.get('amount', 0))
        return math.isfinite(value) and value != 0 and (value < 0 or kind == 'DEBIT')
    except (TypeError, ValueError, OverflowError):
        return False


def _date(transaction):
    value = (
        transaction.get("timestamp")
        or transaction.get("transaction_date")
        or transaction.get("date")
    )

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo('Europe/London'))
        return parsed.date().isoformat()
    except (TypeError, ValueError):
        return None


def _matches(
    subscription,
    transaction,
):
    description = _description(
        transaction
    )

    if not description:
        return False

    terms = subscription.get(
        "match",
        [],
    )

    return _is_debit(transaction) and any(
        str(term).upper()
        in description
        for term in terms
        if term
    )

def _annual_amount_matches(subscription, transaction):
    try:
        amount = float(transaction.get("amount"))
        expected = float(subscription.get("amount"))
    except (TypeError, ValueError):
        return False
    return _is_debit(transaction) and math.isfinite(expected) and abs(abs(amount) - expected) <= 0.01

def update_subscriptions_from_transactions(
    transactions,
):
    """
    Update known subscriptions/bills using
    observed transactions.

    Returns changes that should be printed
    on this receipt.
    """

    data = load_subscriptions()

    changes = []

    changed_file = False

    for frequency in (
        "monthly",
        "yearly",
    ):

        for subscription in data.get(
            frequency,
            [],
        ):

            annual_paid_date = None
            if frequency == "yearly":
                annual_paid_date = annual_subscription_rows(
                    [subscription], transactions,
                    datetime.now(ZoneInfo("Europe/London")).date()
                )[0]["bank_paid_date"]
                if annual_paid_date is None:
                    continue

            matches = [
                tx
                for tx in transactions
                if _matches(
                    subscription,
                    tx,
                )
                and (frequency != "yearly" or
                     (_date(tx) == annual_paid_date.isoformat()
                      and _annual_amount_matches(subscription, tx)))
            ]

            if not matches:
                continue

            # Most recent matching transaction.
            matches.sort(
                key=lambda tx:
                    _date(tx) or "",
                reverse=True,
            )

            transaction = matches[0]

            new_amount = _amount(
                transaction
            )

            paid_date = _date(
                transaction
            )

            if (
                new_amount <= 0
                or not paid_date
            ):
                continue

            old_amount = subscription.get(
                "amount"
            )

            try:
                old_amount = float(
                    old_amount
                )

            except (
                TypeError,
                ValueError,
            ):
                old_amount = None

            # We've already processed this
            # transaction on a previous run.
            if (
                subscription.get(
                    "last_paid"
                )
                == paid_date
            ):
                continue

            history = subscription.setdefault(
                "history",
                [],
            )

            # Record the observed payment.
            history.append({
                "date": paid_date,
                "amount": round(
                    new_amount,
                    2,
                ),
            })

            # Prevent history growing forever.
            subscription["history"] = (
                history[-24:]
            )

            subscription[
                "last_paid"
            ] = paid_date

            changed_file = True

            # First observed payment:
            # initialise without reporting
            # it as a price change.
            if old_amount is None:
                subscription[
                    "amount"
                ] = round(
                    new_amount,
                    2,
                )

                continue

            difference = (
                new_amount
                - old_amount
            )

            # Ignore penny-level noise.
            if abs(difference) < 0.01:
                continue

            if old_amount:
                percentage = (
                    difference
                    / old_amount
                    * 100.0
                )
            else:
                percentage = 0.0

            subscription[
                "amount"
            ] = round(
                new_amount,
                2,
            )

            changes.append({
                "name":
                    subscription.get(
                        "name",
                        "Subscription",
                    ),

                "frequency":
                    frequency,

                "date":
                    paid_date,

                "old_amount":
                    old_amount,

                "new_amount":
                    new_amount,

                "difference":
                    difference,

                "percentage":
                    percentage,
            })

    if changed_file:
        save_subscriptions(
            data
        )

    return changes