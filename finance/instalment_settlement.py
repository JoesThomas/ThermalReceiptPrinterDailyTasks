"""Manual local settlement confirmations; never bank payments or inferred receipts."""

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from finance.money import parse, format_pounds
from finance.repayment_identity import generic_amazon, names

FIELDS = ("remaining_balance", "balance", "payments_remaining", "next_payment")


def identity(row):
    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in row.items() if key != "progress"},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()


def linked_monthly(item, monthly):
    if generic_amazon(item):
        return []
    amount = parse(item.get("monthly_payment", item.get("amount")))
    if amount is None or amount <= 0:
        return []
    matches = [
        (index, row)
        for index, row in enumerate(monthly)
        if not row.get("settled_instalment")
        and names(item) & names(row)
        and parse(row.get("amount")) == amount
    ]
    return (
        [
            dict(
                index=index,
                name=row["name"],
                amount=format_pounds(amount),
                key=identity(row),
            )
            for index, row in matches
        ]
        if len(matches) == 1
        else []
    )


def settle(state, index, key, on, today, *, monthly_key=None):
    rows = state.get("instalments", [])
    if not 0 <= index < len(rows):
        raise ValueError("Instalment not found.")
    row = rows[index]
    if identity(row) != key:
        raise ValueError("This instalment changed. Review it and try again.")
    settled_on = date.fromisoformat(on)
    if settled_on > today:
        raise ValueError("Settlement date cannot be in the future.")
    if row.get("settled_on"):
        raise ValueError("This instalment is already marked settled.")
    linked = linked_monthly(row, state.get("monthly", []))
    if monthly_key and (not linked or linked[0]["key"] != monthly_key):
        raise ValueError(
            "The matching monthly entry changed; review it before settling."
        )
    row["settlement"] = {
        "date": on,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "previous": {name: deepcopy(row[name]) for name in FIELDS if name in row},
        "key": key,
    }
    row.update(
        settled_on=on, remaining_balance=0, payments_remaining=0, next_payment=None
    )
    if "balance" in row:
        row["balance"] = 0
    if monthly_key:
        state["monthly"][linked[0]["index"]].update(
            settled_instalment=key, settled_on=on
        )
    return row["name"]


def reopen(state, index, key):
    rows = state.get("instalments", [])
    if not 0 <= index < len(rows):
        raise ValueError("Instalment not found.")
    row = rows[index]
    if (
        identity(row) != key
        or not row.get("settled_on")
        or not isinstance(row.get("settlement"), dict)
    ):
        raise ValueError("This settlement changed; review it before reopening.")
    previous = row["settlement"]["previous"]
    settlement_key = row["settlement"]["key"]
    on = row["settled_on"]
    for name in FIELDS:
        if name in previous:
            row[name] = deepcopy(previous[name])
        else:
            row.pop(name, None)
    history = row.setdefault("settlement_history", [])
    history.append({k: v for k, v in row["settlement"].items() if k != "previous"})
    row["settlement_history"] = history[-50:]
    row.pop("settlement", None)
    row.pop("settled_on", None)
    for monthly in state.get("monthly", []):
        if (
            monthly.get("settled_instalment") == settlement_key
            and monthly.get("settled_on") == on
        ):
            monthly.pop("settled_instalment", None)
            monthly.pop("settled_on", None)
    return row["name"]


def is_settled(row, today):
    try:
        return bool(
            row.get("settled_instalment")
            and date.fromisoformat(row["settled_on"]) <= today
        )
    except (KeyError, ValueError, TypeError):
        return False
