"""Versioned private subscriptions, preserving existing rows during upgrades."""

from storage import PrivateStore
from datetime import date, datetime
import re
from finance.money import parse


def validate(value):
    if not isinstance(value, dict) or value.get("schema_version", 1) != 1:
        raise ValueError("Unsupported subscription data version")
    for field in ("monthly", "yearly", "instalments"):
        rows = value.get(field, [])
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("Invalid subscription records")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                raise ValueError("Invalid subscription entry")
            if row.get("settled_on") is not None:
                if not isinstance(row["settled_on"], str):
                    raise ValueError("Invalid settlement date")
                date.fromisoformat(row["settled_on"])

            def check_metadata(meta, previous=False):
                if (
                    not isinstance(meta, dict)
                    or not isinstance(meta.get("key"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", meta["key"])
                ):
                    raise ValueError("Invalid settlement metadata")
                if not isinstance(meta.get("date"), str) or not isinstance(
                    meta.get("recorded_at"), str
                ):
                    raise ValueError("Invalid settlement dates")
                date.fromisoformat(meta["date"])
                if datetime.fromisoformat(meta["recorded_at"]).tzinfo is None:
                    raise ValueError("Invalid settlement timestamp")
                if previous and (
                    not isinstance(meta.get("previous"), dict)
                    or set(meta["previous"])
                    - {
                        "balance",
                        "remaining_balance",
                        "payments_remaining",
                        "next_payment",
                    }
                ):
                    raise ValueError("Invalid previous settlement fields")
                if previous:
                    for key in ("balance", "remaining_balance"):
                        if (
                            key in meta["previous"]
                            and meta["previous"][key] is not None
                            and parse(meta["previous"][key]) is None
                        ):
                            raise ValueError("Invalid previous settlement balance")

            if "settlement" in row:
                check_metadata(row["settlement"], previous=True)
                if (
                    row.get("settled_on") != row["settlement"]["date"]
                    or parse(row.get("remaining_balance")) != 0
                    or row.get("payments_remaining") != 0
                ):
                    raise ValueError("Invalid settled instalment balance")
            if "settled_instalment" in row and (
                not isinstance(row["settled_instalment"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["settled_instalment"])
                or not row.get("settled_on")
            ):
                raise ValueError("Invalid linked settlement")
            history = row.get("settlement_history", [])
            if not isinstance(history, list) or len(history) > 50:
                raise ValueError("Invalid settlement history")
            for meta in history:
                check_metadata(meta)
            for key in (
                "amount",
                "monthly_payment",
                "remaining_balance",
                "paid_to_date",
                "total_price",
            ):
                if row.get(key) is not None and parse(row[key]) is None:
                    raise ValueError("Invalid subscription amount")


def legacy(value):
    return {"monthly": [], "yearly": [], "instalments": [], **value}


def store(path):
    return PrivateStore(
        path,
        default=lambda: legacy({}),
        validate=validate,
        schema_version=1,
        migrations={0: legacy},
    )


def load(path):
    return store(path).read()


def save(path, value):
    validate(value)

    def replace(current):
        current.clear()
        current.update(value)

    store(path).update(replace)
