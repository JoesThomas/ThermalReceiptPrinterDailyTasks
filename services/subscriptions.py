from __future__ import annotations

import json

from datetime import datetime
from pathlib import Path


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
    SUBSCRIPTIONS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        SUBSCRIPTIONS_FILE
        .with_suffix(".tmp")
    )

    with temporary.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )

        file.write("\n")

    temporary.replace(
        SUBSCRIPTIONS_FILE
    )


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
        return abs(
            float(
                transaction.get(
                    "amount",
                    0,
                )
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return 0.0


def _date(transaction):
    value = (
        transaction.get("timestamp")
        or transaction.get("date")
    )

    if not value:
        return None

    try:
        return (
            datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
            .date()
            .isoformat()
        )

    except (
        TypeError,
        ValueError,
    ):
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

    return any(
        str(term).upper()
        in description
        for term in terms
        if term
    )

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

            matches = [
                tx
                for tx in transactions
                if _matches(
                    subscription,
                    tx,
                )
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