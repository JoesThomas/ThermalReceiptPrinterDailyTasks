"""Gross AER growth estimates; no bank movements or contribution allowance use."""

from datetime import timedelta
from decimal import Decimal
from finance.money import rounded
from finance.projection import day, money

ZERO = Decimal(0)
ONE = Decimal(1)


def has_recorded_rate(row):
    """Accounts whose recorded AER is used by the savings interest model."""
    return (row['type'] in {'savings', 'cash_isa'}
            and row.get('interest_rate') is not None
            and not row.get('cash_reserve_limit'))


def render_account_interest(page, row):
    if has_recorded_rate(row):
        page.amount('  Interest over forecast',
                    row.get('estimated_interest') if row['balance'] is not None else None)


class Growth:
    def __init__(self, rows, start, goal=None):
        self.rows = rows
        self.on = start
        self.goal = goal
        self.goal_date = None
        self.factors = {}
        for row in rows:
            row.setdefault("projected", row["balance"])
            row.setdefault("goal_date", None)
            row["estimated_interest"] = ZERO
            rate = money(row.get("interest_rate"), ZERO)
            if (
                start
                and row["type"] in {"savings", "cash_isa"}
                and not row.get("cash_reserve_limit")
                and rate > 0
            ):
                self.factors[row["id"]] = (ONE + rate / 100) ** (ONE / 365)
        self.check(start)

    def value(self, row, on):
        value = row["projected"]
        factor = self.factors.get(row["id"])
        if value is None or factor is None or self.on is None:
            return value
        start = max(self.on, day(row.get("rate_date")) or self.on)
        days = max(0, (on - start).days)
        return value * factor**days

    def check(self, on):
        if (
            self.goal
            and self.goal_date is None
            and sum(
                (row["projected"] for row in self.rows if row["projected"] is not None),
                ZERO,
            )
            >= self.goal
        ):
            self.goal_date = on

    def advance(self, on):
        if self.on is None or on <= self.on:
            return
        if not self.factors:
            self.on = on
            return

        # Binary search within event intervals also finds targets met by interest alone.
        def crossing(predicate):
            low, high = 1, (on - self.on).days
            while low < high:
                mid = (low + high) // 2
                if predicate(self.on + timedelta(days=mid)):
                    high = mid
                else:
                    low = mid + 1
            return self.on + timedelta(days=low)

        for row in self.rows:
            if row["projected"] is None:
                continue
            value = self.value(row, on)
            target = row.get("target")
            if target and row.get("goal_date") is None and rounded(value) >= target:
                row["goal_date"] = crossing(
                    lambda stamp: rounded(self.value(row, stamp)) >= target
                )
        if (
            self.goal
            and self.goal_date is None
            and sum(
                (
                    rounded(self.value(row, on))
                    for row in self.rows
                    if row["projected"] is not None
                ),
                ZERO,
            )
            >= self.goal
        ):
            self.goal_date = crossing(
                lambda stamp: (
                    sum(
                        (
                            rounded(self.value(row, stamp))
                            for row in self.rows
                            if row["projected"] is not None
                        ),
                        ZERO,
                    )
                    >= self.goal
                )
            )
        for row in self.rows:
            if row["projected"] is not None:
                value = self.value(row, on)
                row["estimated_interest"] += value - row["projected"]
                row["projected"] = value
        self.on = on
        self.check(on)

    def finish(self):
        for row in self.rows:
            if row["projected"] is not None:
                row["estimated_interest"] = rounded(row["estimated_interest"])
                row["projected"] = (
                    row["balance"] + row.get("added", ZERO) + row["estimated_interest"]
                )
