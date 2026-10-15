"""Private per-account overrides for overdraft included in available balances."""

from pathlib import Path

from finance.money import parse
from storage import PrivateStore, write_json

FILE = Path(__file__).resolve().parents[1] / "data" / "bank_overdrafts.json"


def validate(value):
    if not isinstance(value, dict) or set(value) - {"HSBC", "MONZO"}:
        raise ValueError("Invalid overdraft settings.")
    for accounts in value.values():
        if not isinstance(accounts, dict) or len(accounts) > 100:
            raise ValueError("Invalid overdraft accounts.")
        for identity, limit in accounts.items():
            amount = parse(limit, rounded=False)
            if (
                not isinstance(identity, str)
                or not 1 <= len(identity) <= 200
                or amount is None
                or not 0 <= amount <= 10000000
            ):
                raise ValueError("Enter an overdraft limit between £0 and £10,000,000.")


def load():
    return PrivateStore(FILE, default=dict, validate=validate).read()


def save(values):
    validate(values)
    from finance.bank_accounts import catalog

    known = {(row["provider"], row["id"]) for row in catalog()["accounts"]}
    if any(
        (provider, identity) not in known
        for provider, accounts in values.items()
        for identity in accounts
    ):
        raise ValueError("Choose accounts from the latest bank check.")
    write_json(FILE, values)


def cash_balance(row, override=None):
    """Exclude borrowing once, retaining pending holds and negative balances."""
    from finance.bank_accounts import number

    current = number(row.get("current"))
    available = number(row.get("available", current))
    limit = (
        number(override)
        if override is not None
        else number(row["overdraft"] if row.get("overdraft") is not None else 0)
    )
    if limit < 0:
        raise ValueError("Invalid overdraft limit returned by bank.")
    # Current excludes pending payments; an available balance may include credit.
    # If available is absent, current is already the owned balance: don't deduct again.
    adjusted = available - limit if "available" in row else current
    return current, min(current, adjusted), available, limit
