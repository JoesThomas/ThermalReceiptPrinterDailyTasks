"""Named manual forecast inputs, separate from generated results and bank data."""

from datetime import date, datetime, timezone
from pathlib import Path
import re
import uuid
from finance.scenario_inputs import validate
from finance.projection import money
from storage import PrivateStore, validate_schema_version

FILE = Path(__file__).resolve().parents[1] / "data" / "finance_scenarios.json"
FIELDS = frozenset(
    "receipt_detail respect_isa_allowance isa_over_65 monzo_target monzo_balance salary mode lump_sum existing_salary other_income start months strategy amex_split amex_apr savings_target save_all invest_spare_cash savings_goal use_saved_accounts equal_savings starting_savings hl_account hl_monthly salary_start salary_end missed_salary_dates comparison_spend one_off_expenses amex_owed opening_cash daily_spend".split()
)
CHECKBOXES = ("respect_isa_allowance", "isa_over_65", "save_all", "invest_spare_cash", "equal_savings", "use_saved_accounts")


def inputs(values):
    result = {
        key: value
        for key, value in values.items()
        if key in FIELDS or key.startswith("payment_account_")
    }
    for key in CHECKBOXES:
        result.setdefault(key, "")
    if len(result) > 80 or any(
        not isinstance(v, str) or len(v) > 10000 for v in result.values()
    ):
        raise ValueError("Scenario inputs are too large.")
    if sum(len(k) + len(v) for k, v in result.items()) > 30000:
        raise ValueError("Scenario inputs are too large.")
    return result


def validate_inputs(values, on):
    if not isinstance(values, dict) or inputs(values) != values:
        raise ValueError("Invalid saved scenario inputs.")
    validate(values, on)
    for field, limit in (
        ("opening_cash", 10000000),
        ("daily_spend", 100000),
        ("amex_owed", 10000000),
    ):
        raw = values.get(field, "").strip()
        value = money(raw)
        if raw and (value is None or not 0 <= value <= limit):
            raise ValueError(f"Enter a valid {field.replace('_', ' ')}.")


def validate_state(state):
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("scenarios"), dict)
        or len(state["scenarios"]) > 50
    ):
        raise ValueError("Use at most 50 saved scenarios.")
    validate_schema_version(state, 1)
    names = set()
    for identifier, row in state["scenarios"].items():
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-f0-9]{32}", identifier)
            or not isinstance(row, dict)
        ):
            raise ValueError("Invalid saved scenario.")
        name = row.get("name")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 60
            or name != name.strip()
            or any(ord(c) < 32 for c in name)
            or name.casefold() in names
        ):
            raise ValueError("Choose a unique scenario name up to 60 characters.")
        names.add(name.casefold())
        saved = datetime.fromisoformat(row["saved_at"])
        if saved.tzinfo is None:
            raise ValueError("Invalid scenario timestamp.")
        validate_inputs(row["values"], date.fromisoformat(row["validated_on"]))


def store():
    return PrivateStore(
        FILE,
        default=lambda: {"scenarios": {}},
        validate=validate_state,
        max_bytes=900000,
        schema_version=1,
        migrations={0: lambda value: value},
    )


def save(name, values, today):
    name = name.strip()
    values = inputs(values)
    validate_inputs(values, today)
    identifier = uuid.uuid4().hex

    def change(state):
        nonlocal identifier
        existing = next(
            (
                key
                for key, row in state["scenarios"].items()
                if row["name"].casefold() == name.casefold()
            ),
            None,
        )
        identifier = existing or identifier
        state["scenarios"][identifier] = {
            "name": name,
            "values": values,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "validated_on": today.isoformat(),
        }

    store().update(change)
    return identifier


def load(identifier):
    row = store().read()["scenarios"].get(identifier)
    if row is None:
        raise ValueError("Saved scenario unavailable.")
    return row


def delete(identifier):
    def change(state):
        if identifier not in state["scenarios"]:
            raise ValueError("Saved scenario unavailable.")
        del state["scenarios"][identifier]

    store().update(change)


def listing():
    return [
        dict(
            id=key,
            name=row["name"],
            saved_at=row["saved_at"],
            start=row["values"]["start"],
        )
        for key, row in sorted(
            store().read()["scenarios"].items(),
            key=lambda item: item[1]["name"].casefold(),
        )
    ]
