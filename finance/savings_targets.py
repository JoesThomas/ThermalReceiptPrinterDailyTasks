"""Read-only account snapshots and non-overlapping hypothetical goal allocation."""

from decimal import Decimal, ROUND_DOWN
from finance.money import rounded
from pathlib import Path
from copy import deepcopy
import re
from finance.projection import money, day

ZERO = Decimal(0)
CENT = Decimal("0.01")


def load_view(today):
    from finance.wealth_history import review
    from finance.savings_goals import review as goals_review, identity
    from savings_runway import load_savings
    from finance.investments import load_investments

    root = Path(__file__).resolve().parents[1]
    wealth = review(today)
    known = {identity(row["name"], row["kind"]) for row in wealth["accounts"]}
    for kind, data in [
        ("savings", load_savings(root / "data" / "savings.json")),
        ("investment", load_investments()),
    ]:
        for row in data.get("accounts", []):
            if not isinstance(row, dict) or not row.get("name"):
                continue
            key = identity(row["name"], kind)
            balance = money(row.get("balance"))
            if key in known or balance is None or balance < 0:
                continue
            wealth["accounts"].append(
                dict(
                    row,
                    kind=kind,
                    balance=balance,
                    latest={"date": data.get("updated") or ""},
                )
            )
            known.add(key)
    view = goals_review(wealth, on=today)
    rows = []
    for account in view["accounts"]:
        target = money(account.get("target"))
        if account["type"] == "premium_bonds":
            target = min(target or Decimal(50000), Decimal(50000))
        rows.append(
            {
                "id": account["id"],
                "name": account["name"],
                "kind": account["kind"],
                "type": account["type"],
                "balance": money(account.get("balance")),
                "date": account.get("balance_date"),
                "target": target,
                "share": money(account.get("monthly_share"), ZERO),
                "isa_contributions": account.get("contributions", ZERO)
                if account["type"] in {"cash_isa", "stocks_isa", "other_isa"}
                else None,
            }
        )
    return rows


def payment_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def is_hargreaves(value):
    key = payment_key(value)
    return (
        "hargreaves" in key
        or key.startswith(("hlam", "handl", "hlisa"))
        or key == "hl"
        or bool(re.search(r"\bh\s*(?:&|and)\s*l\b|\bhl\b", str(value), re.I))
    )


def link_regular_savings(events, accounts, payment_accounts=None):
    """Explicit account IDs take priority; ambiguous automatic matches stay unlinked."""
    mappings = payment_accounts or {}
    known = {row["id"]: row for row in accounts}
    if any(identifier not in known for identifier in mappings.values()):
        raise ValueError(
            "Choose a recorded account with a known balance for scheduled savings."
        )
    for event in events:
        if event.get("scenario_expense") or event.get("amount", ZERO) <= 0:
            continue
        identifier = mappings.get(payment_key(event["name"])) or event.get(
            "savings_account"
        )
        if identifier:
            if identifier not in known:
                raise ValueError(
                    "The scheduled savings account is unavailable; choose its destination again."
                )
            event["savings_account"] = identifier
            continue
        candidates = [
            row
            for row in accounts
            if payment_key(row["name"]) == payment_key(event["name"])
            or (is_hargreaves(row["name"]) and is_hargreaves(event["name"]))
        ]
        if len(candidates) == 1 and (
            event.get("category") == "savings" or is_hargreaves(event["name"])
        ):
            event["savings_account"] = candidates[0]["id"]


def prepare_cash_topup(base, accounts, today, start):
    """Align a single physical cash goal and reserve without another cash charge."""
    reserve = base.get("reserve_details")
    if not reserve or not money(reserve.get("target")):
        return
    aliases = {
        "cash",
        "physical cash",
        "cash on hand",
        "cash in hand",
        "cash at home",
        "cash reserve",
        "cash savings",
        "cash stash",
        "cash pot",
    }
    candidates = [
        row
        for row in accounts
        if row["kind"] == "savings"
        and row["type"] == "savings"
        and " ".join(row["name"].casefold().split()) in aliases
    ]
    if len(candidates) != 1:
        return
    account = candidates[0]
    account_date = day(account.get("date"))
    reserve_date = day(reserve.get("date"))
    held = money(reserve.get("held"))
    if (
        held is not None
        and reserve_date
        and reserve_date <= today
        and (not account_date or reserve_date > account_date)
    ):
        account["balance"] = held
        account["date"] = reserve_date.isoformat()
    elif account["balance"] is not None:
        held = account["balance"]
    else:
        return
    gap = max(ZERO, money(reserve["target"]) - held)
    base["buffer"] += gap - money(reserve.get("gap"), ZERO)
    reserve.update(held=held, gap=gap, date=day(account.get("date")))
    if gap:
        base["cash_topup"] = {
            "savings_account": account["id"],
            "amount": gap,
            "date": today if base["cash"] >= base["buffer"] else start,
            "reserved_cash_topup": True,
        }


def allocate(accounts, periods, automatic_events=(), *, equal=False):
    rows = deepcopy(accounts)
    for row in rows:
        if row["type"] == "premium_bonds":
            row["target"] = min(row["target"] or Decimal(50000), Decimal(50000))
        row.update(
            allocations=[],
            projected=row["balance"],
            added=ZERO,
            first=ZERO,
            automatic_added=ZERO,
            first_automatic=ZERO,
            reserved_added=ZERO,
            goal_date=None,
        )
        if (
            row["target"]
            and row["balance"] is not None
            and row["balance"] >= row["target"]
        ):
            row["goal_date"] = "already"
    explicit = not equal and any(row["share"] > 0 for row in rows)
    fraction = (
        min(
            Decimal(100),
            sum(
                (row["share"] for row in rows if row["balance"] is not None),
                ZERO,
            ),
        )
        / 100
        if explicit
        else Decimal(1)
    )
    by_id = {row["id"]: row for row in rows}
    unallocated = ZERO
    timeline = [
        (period["date"], 1, index, period) for index, period in enumerate(periods)
    ]
    timeline += [
        (event["date"], 0, None, event)
        for event in automatic_events
        if event.get("savings_account")
    ]
    for on, kind, index, period in sorted(
        timeline, key=lambda item: (item[0], item[1])
    ):
        if kind == 0:
            row = by_id.get(period["savings_account"])
            if row is None or row["projected"] is None:
                continue
            part = period["amount"]
            row["projected"] += part
            row["added"] += part
            if period.get("reserved_cash_topup"):
                row["reserved_added"] += part
            else:
                row["automatic_added"] += part
                if periods and periods[0]["date"] <= on <= periods[0]["end"]:
                    row["first_automatic"] += part
            if (
                row["target"]
                and row["projected"] >= row["target"]
                and row["goal_date"] is None
                and period.get("funded", True)
            ):
                row["goal_date"] = on
            continue
        before = {row["id"]: row["added"] for row in rows}
        amount = period["savings"]
        budget = period.get("savings_budget", amount)
        remaining = rounded(budget * fraction, rounding=ROUND_DOWN)
        assigned = ZERO
        # Reserve room for already scheduled Premium Bonds payments. Their hard
        # holding cap applies even when a balance goal was set higher.
        room = {
            row["id"]: max(
                ZERO,
                row["target"]
                - row["projected"]
                - sum(
                    (
                        event["amount"]
                        for event in automatic_events
                        if event.get("savings_account") == row["id"]
                        and event["date"] > on
                    ),
                    ZERO,
                )
                if row["type"] == "premium_bonds"
                else row["target"] - row["projected"]
                if row["target"]
                else remaining,
            )
            for row in rows
            if row["projected"] is not None
        }
        while remaining >= CENT:
            eligible = [
                row
                for row in rows
                if row["projected"] is not None
                and room.get(row["id"], ZERO) > ZERO
                and (not explicit or row["share"] > 0)
            ]
            if not eligible:
                break
            weights = sum(
                (row["share"] if explicit else Decimal(1) for row in eligible), ZERO
            )
            available = remaining
            progressed = ZERO
            for row in eligible:
                part = rounded(
                    available * (row["share"] if explicit else Decimal(1)) / weights,
                    rounding=ROUND_DOWN,
                )
                part = min(part, room[row["id"]])
                if not part and remaining >= CENT:
                    part = min(CENT, room[row["id"]])
                part = min(part, remaining)
                row["projected"] += part
                row["added"] += part
                if index == 0:
                    row["first"] += part
                remaining -= part
                room[row["id"]] -= part
                assigned += part
                progressed += part
                if (
                    row["target"]
                    and row["projected"] >= row["target"]
                    and row["goal_date"] is None
                ):
                    row["goal_date"] = (
                        period["date"] if period.get("funded", True) else None
                    )
            if progressed == 0:
                break
        for row in rows:
            part = row["added"] - before[row["id"]]
            income = (
                min(
                    part,
                    rounded(
                        part * period.get("income_savings", amount) / amount,
                        rounding=ROUND_DOWN,
                    ),
                )
                if amount
                else ZERO
            )
            row["allocations"].append(
                {"date": on, "total": part, "income": income, "cash": part - income}
            )
        unallocated += max(ZERO, amount - assigned)
    return {
        "accounts": rows,
        "unallocated": unallocated,
        "current_total": sum(
            (row["balance"] for row in rows if row["balance"] is not None), ZERO
        ),
        "projected_total": sum(
            (row["projected"] for row in rows if row["projected"] is not None), ZERO
        ),
        "complete": all(row["balance"] is not None for row in rows),
    }
