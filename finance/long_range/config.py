"""Strict, versioned assumptions for private monthly long-term plans."""

from datetime import date, timedelta
from finance.projection import occurs
from decimal import Decimal
from finance.money import parse
import re
import uuid

KINDS = (
    "bank",
    "cash",
    "savings",
    "cash_isa",
    "stocks_isa",
    "investment",
    "premium_bonds",
    "pension",
    "property",
    "debt",
)
EVENTS = (
    "salary",
    "other_income",
    "bills",
    "spending",
    "cost",
    "income",
    "withdraw",
    "contribution",
    "realise_payout",
    "asset_purchase",
)
NUMBERS = dict(
    balance="0",
    target="0",
    limit="",
    monthly="0",
    low="0",
    expected="0",
    high="0",
    fee="0",
    tax="0",
    yield_rate="0",
    apr="0",
    isa_used="0",
)


def account(name="New account", kind="savings", **changes):
    return dict(
        dict(
            id=uuid.uuid4().hex[:12],
            name=name,
            kind=kind,
            stop=False,
            early=False,
            unlock="",
            payout="self",
            scheduled=False,
            extra=kind not in {"bank", "cash", "pension", "property", "debt"},
            **NUMBERS,
        ),
        **changes,
    )


def defaults(today):
    return dict(
        name="Long-term plan",
        start=today.isoformat(),
        reviewed=today.isoformat(),
        years="20",
        inflation="2",
        salary="0",
        other_income="0",
        bills="0",
        spending="0",
        debt_spending="700",
        income_growth="0",
        spending_growth="0",
        minimum="500",
        isa_allowance="20000",
        cash_isa_limit="20000",
        isa_enabled=True,
        invest_without_salary=False,
        accounts=[account("Bank cash", "bank", target="1000")],
        events=[],
        goals=[],
    )


def number(raw, low=0, high=100000000):
    value = parse(raw)
    if value is None or not Decimal(low) <= value <= Decimal(high):
        raise ValueError(f"Enter a finite number from {low} to {high}.")
    return value


def label(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 90
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Use a short name without control characters.")
    return value.strip()


def validate(raw):
    if not isinstance(raw, dict):
        raise ValueError("Invalid long-term plan.")
    v = dict(raw)
    v["name"] = label(v.get("name", ""))
    start = date.fromisoformat(v["start"])
    date.fromisoformat(v["reviewed"])
    years = int(v["years"])
    if not 1 <= years <= 40 or start.year + years > 9998:
        raise ValueError("Choose 1 to 40 years.")
    for key in (
        "salary",
        "other_income",
        "bills",
        "spending",
        "debt_spending",
        "minimum",
        "isa_allowance",
        "cash_isa_limit",
    ):
        number(v[key])
    for key in ("inflation", "income_growth", "spending_growth"):
        number(v[key], -20, 30)
    for key in ("isa_enabled", "invest_without_salary"):
        if type(v[key]) is not bool:
            raise ValueError("Invalid planning switch.")
    for key, maximum in [("accounts", 40), ("events", 100), ("goals", 50)]:
        if not isinstance(v.get(key), list) or len(v[key]) > maximum:
            raise ValueError("Too many " + key + ".")
    ids = set()
    names = set()
    for row in v["accounts"]:
        if (
            not isinstance(row, dict)
            or not re.fullmatch("[a-f0-9]{12}", row.get("id", ""))
            or row["id"] in ids
        ):
            raise ValueError("Invalid account identifier.")
        ids.add(row["id"])
        name = label(row["name"])
        if name.casefold() in names:
            raise ValueError("Account names must be unique.")
        names.add(name.casefold())
        if row["kind"] not in KINDS:
            raise ValueError("Invalid account type.")
        for key in NUMBERS:
            if key == "limit" and row[key] == "":
                continue
            number(
                row[key],
                -50
                if key in ("low", "expected", "high")
                and row["kind"]
                not in ("premium_bonds", "debt", "savings", "cash_isa", "bank", "cash")
                else 0,
                50
                if key in ("low", "expected", "high")
                else 100
                if key in ("apr", "tax", "yield_rate")
                else 10
                if key == "fee"
                else 100000000,
            )
        if (
            not number(row["low"], -50, 50)
            <= number(row["expected"], -50, 50)
            <= number(row["high"], -50, 50)
        ):
            raise ValueError("Use lower ≤ expected ≤ higher returns.")
        if row["unlock"]:
            date.fromisoformat(row["unlock"])
        if (
            type(row["stop"]) is not bool
            or type(row["early"]) is not bool
            or type(row["scheduled"]) is not bool
            or type(row["extra"]) is not bool
        ):
            raise ValueError("Invalid account switch.")
        if row["kind"] == "premium_bonds" and number(row["balance"]) > 50000:
            raise ValueError("Premium Bonds cannot exceed £50,000.")
        if row["kind"] == "bank" and number(row["balance"]) < 0:
            raise ValueError("Record an overdraft as a debt, not spendable cash.")
        if row["kind"] == "pension" and not row["unlock"]:
            raise ValueError(
                "Set a pension access date; this planner does not infer eligibility."
            )
    if not any(a["kind"] == "bank" for a in v["accounts"]):
        raise ValueError("Keep at least one bank account.")
    accessible = {
        a["id"]
        for a in v["accounts"]
        if a["kind"]
        in (
            "bank",
            "cash",
            "savings",
            "cash_isa",
            "stocks_isa",
            "investment",
            "premium_bonds",
        )
    }
    for row in v["accounts"]:
        if row["payout"] not in {"self", "bank"} | accessible:
            raise ValueError("Choose a valid payout destination.")
    end = occurs(start, years * 12) - timedelta(days=1)
    for row in v["events"]:
        label(row["name"])
        on = date.fromisoformat(row["date"])
        if row["kind"] not in EVENTS or on < start or on > end:
            raise ValueError("Use an event within the planning horizon.")
        number(row["amount"])
        repeat = int(row["repeat"])
        if not 0 <= repeat <= 480:
            raise ValueError("Repeat every 0–480 months; 0 means once.")
        if (
            row["kind"]
            in ("withdraw", "contribution", "realise_payout", "asset_purchase")
            and row["account"] not in ids
        ):
            raise ValueError("Choose the event account.")
    for row in v["goals"]:
        label(row["name"])
        number(row["amount"])
        if row["account"] not in ids:
            raise ValueError("Choose the goal account.")
        on = date.fromisoformat(row["date"])
        if on < start or on > end:
            raise ValueError("Goal date must be within the planning horizon.")
        if type(row["inflates"]) is not bool:
            raise ValueError("Invalid inflation switch.")
    return v
