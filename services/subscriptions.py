from __future__ import annotations

from datetime import datetime
from pathlib import Path

from data_store import edit_json, read_json, write_json


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

SUBSCRIPTIONS_FILE = (
    PROJECT_ROOT
    / "data"
    / "subscriptions.json"
)

def _default_subscriptions():
    return {
        "monthly": [],
        "yearly": [],
        "instalments": [],
    }


def _normalise_data(data):
    if not isinstance(data, dict):
        raise ValueError(
            "data/subscriptions.json must contain a JSON object."
        )

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


def load_subscriptions():
    data = read_json(
        SUBSCRIPTIONS_FILE,
        _default_subscriptions(),
    )
    return _normalise_data(
        data
    )


def save_subscriptions(data):
    write_json(
        SUBSCRIPTIONS_FILE,
        _normalise_data(
            data
        ),
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

def _transaction_id(transaction):
    for key in (
        "transaction_id",
        "normalised_provider_transaction_id",
        "provider_transaction_id",
        "id",
    ):
        value = transaction.get(
            key
        )

        if value:
            return str(
                value
            )

    paid_date = _date(
        transaction
    ) or ""

    amount = _amount(
        transaction
    )

    description = _description(
        transaction
    )

    return (
        f"fallback:{paid_date}:"
        f"{amount:.2f}:{description}"
    )


def update_subscriptions_from_transactions(
    transactions,
):
    """
    Update existing known subscriptions/bills from
    observed transactions.

    Transactions are de-duplicated using their provider
    transaction ID where available, falling back to
    date + amount + description.
    """
    changes = []

    with edit_json(
        SUBSCRIPTIONS_FILE,
        _default_subscriptions(),
    ) as data:
        _normalise_data(
            data
        )

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

                transaction_id = (
                    _transaction_id(
                        transaction
                    )
                )

                history = subscription.setdefault(
                    "history",
                    [],
                )

                if any(
                    entry.get(
                        "transaction_id"
                    )
                    == transaction_id
                    for entry in history
                    if isinstance(
                        entry,
                        dict,
                    )
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

                history.append({
                    "date": paid_date,
                    "amount": round(
                        new_amount,
                        2,
                    ),
                    "transaction_id":
                        transaction_id,
                })

                subscription["history"] = (
                    history[-24:]
                )

                subscription[
                    "last_paid"
                ] = paid_date

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

                if abs(
                    difference
                ) < 0.01:
                    continue

                percentage = (
                    (
                        difference
                        / old_amount
                        * 100.0
                    )
                    if old_amount
                    else 0.0
                )

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
                    "transaction_id":
                        transaction_id,
                })

    return changes
