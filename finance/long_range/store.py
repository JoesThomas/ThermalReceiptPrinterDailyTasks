"""Versioned private assumptions and dated observations; no credentials or documents."""

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from storage import PrivateStore
from finance.long_range.config import validate, label, number

FILE = Path(__file__).resolve().parents[2] / "data" / "long_term_plans.json"


def validate_state(state):
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or not isinstance(state.get("plans"), dict)
        or not isinstance(state.get("observations"), list)
    ):
        raise ValueError("Unsupported long-term planning records.")
    if (
        len(state["plans"]) > 12
        or len(state["observations"]) > 1000
        or len(json.dumps(state)) > 250000
    ):
        raise ValueError(
            "Planning history is full; remove an older saved plan or observation first."
        )
    for key, row in state["plans"].items():
        if not re.fullmatch("[a-f0-9]{12}", key):
            raise ValueError("Invalid saved plan.")
        validate(row["config"])
        stamp = datetime.fromisoformat(row["saved_at"])
        if stamp.tzinfo is None:
            raise ValueError("Invalid baseline timestamp.")
    for row in state["observations"]:
        if not re.fullmatch("[a-f0-9]{12}", row["account"]):
            raise ValueError("Invalid observed account.")
        date.fromisoformat(row["date"])
        number(row["balance"])
        label(row["note"] or "Observation")


def store():
    return PrivateStore(
        FILE,
        default=lambda: dict(schema_version=1, plans={}, observations=[]),
        validate=validate_state,
        max_bytes=250000,
    )


def save(config):
    config = validate(config)
    key = uuid.uuid4().hex[:12]

    def update(state):
        state["plans"][key] = dict(
            config=config, saved_at=datetime.now(timezone.utc).isoformat()
        )

    store().update(update)
    return key


def observe(account, on, balance, note, today):
    if date.fromisoformat(on) > today:
        raise ValueError("Actual balances cannot be dated in the future.")
    value = dict(
        account=account,
        date=on,
        balance=str(number(balance)),
        note=label(note) if note else "",
    )

    def update(state):
        if account not in {
            a["id"] for p in state["plans"].values() for a in p["config"]["accounts"]
        }:
            raise ValueError("Save the plan before recording actual balances.")
        state["observations"] = [
            r
            for r in state["observations"]
            if (r["account"], r["date"]) != (account, on)
        ] + [value]

    store().update(update)
