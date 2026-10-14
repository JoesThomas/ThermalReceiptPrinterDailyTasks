"""Dated subscription headroom, separate from ISA balances and account caps."""

from copy import deepcopy
from decimal import Decimal
from finance.savings_goals import ISA, tax_year
from finance.projection import money

ZERO = Decimal(0)


def allowance_snapshot(accounts, today, state=None, *, over_65=False):
    years = {}
    state = state or {}
    for year in range(tax_year(today), tax_year(today) + 7):
        config = state.get("years", {}).get(str(year), {})
        standard_cash = (
            Decimal(12000) if year >= 2027 and not over_65 else Decimal(20000)
        )
        shared = min(Decimal(20000), money(config.get("allowance"), Decimal(20000)))
        cash = min(standard_cash, money(config.get("cash_limit"), standard_cash))
        used, cash_used, lifetime_used = ZERO, ZERO, ZERO
        if "entries" in state:
            for entry in state["entries"]:
                from datetime import date

                stamp = date.fromisoformat(entry["date"])
                kind = entry.get(
                    "isa_type",
                    state.get("accounts", {}).get(entry["account"], {}).get("type"),
                )
                if stamp > today or tax_year(stamp) != year or kind not in ISA:
                    continue
                value = money(entry["amount"], ZERO)
                name = (
                    state.get("accounts", {}).get(entry["account"], {}).get("name", "")
                )
                lifetime = "lifetime" in name.casefold() or name.casefold() == "lisa"
                if lifetime and entry["event"] in {"contribution", "transfer"}:
                    lifetime_used += value
                if entry["event"] != "contribution":
                    continue
                used += value
                if kind == "cash_isa":
                    cash_used += value
        elif year == tax_year(today):
            for row in accounts:
                if row["type"] not in ISA:
                    continue
                value = money(row.get("isa_contributions"), ZERO)
                used += value
                if row["type"] == "cash_isa":
                    cash_used += value
                if is_lifetime(row):
                    lifetime_used += value
        years[year] = dict(
            allowance=shared,
            cash_limit=min(shared, cash),
            used=used,
            cash_used=cash_used,
            lifetime_used=lifetime_used,
        )
    return years


def is_lifetime(row):
    return "lifetime" in row["name"].casefold() or row["name"].casefold() == "lisa"


def is_isa(row):
    return row["type"] in ISA or row["type"] == "junior_isa"


class Headroom:
    def __init__(self, limits=None):
        self.years = deepcopy(limits) if limits is not None else None

    def shared_room(self, on, scheduled=()):
        return self.room({"type": "stocks_isa", "name": ""}, on, scheduled)

    def cash_room(self, on, scheduled=()):
        return self.room({"type": "cash_isa", "name": ""}, on, scheduled)

    def room(self, row, on, scheduled=()):
        if self.years is None or not is_isa(row):
            return None
        if (
            row["type"] == "junior_isa"
            or is_lifetime(row)
            or "help to buy" in row["name"].casefold()
        ):
            return ZERO
        year = tax_year(on)
        state = self.years.get(year)
        if state is None:
            return ZERO
        shared, cash, lifetime = ZERO, ZERO, ZERO
        for event, account in scheduled:
            if (
                event["date"] <= on
                or tax_year(event["date"]) != year
                or not is_isa(account)
            ):
                continue
            shared += event["amount"]
            if account["type"] == "cash_isa":
                cash += event["amount"]
            if is_lifetime(account):
                lifetime += event["amount"]
        room = max(ZERO, state["allowance"] - state["used"] - shared)
        if row["type"] == "cash_isa":
            room = min(room, max(ZERO, state["cash_limit"] - state["cash_used"] - cash))
        if is_lifetime(row):
            room = min(
                room, max(ZERO, Decimal(4000) - state["lifetime_used"] - lifetime)
            )
        return room

    def use(self, row, on, amount):
        if self.years is None or not is_isa(row):
            return
        state = self.years[tax_year(on)]
        state["used"] += amount
        if row["type"] == "cash_isa":
            state["cash_used"] += amount
        if is_lifetime(row):
            state["lifetime_used"] += amount
