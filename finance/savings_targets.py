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
                "label": account.get("label", account["name"]),
                "kind": account["kind"],
                "type": account["type"],
                "balance": money(account.get("balance")),
                "date": account.get("balance_date"),
                "target": target,
                "balance_limit": money(account.get("balance_limit")),
                "interest_rate": money(account.get("interest_rate")),
                "rate_date": account.get("rate_date"),
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
    account["cash_reserve_limit"] = money(reserve["target"])
    explicit_limit = money(account.get("balance_limit"))
    if explicit_limit is not None and explicit_limit < account["cash_reserve_limit"]:
        raise ValueError(
            "Cash account maximum is below its protected cash reserve target. Adjust those settings first."
        )
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


def contribution_limit(row):
    limit = money(row.get("balance_limit"))
    if row["type"] == "premium_bonds":
        limit = min(limit, Decimal(50000)) if limit is not None else Decimal(50000)
    cash_limit = money(row.get("cash_reserve_limit"))
    if cash_limit is not None:
        limit = min(limit, cash_limit) if limit is not None else cash_limit
    return limit


def allocate(
    accounts,
    periods,
    automatic_events=(),
    *,
    equal=False,
    isa_limits=None,
    start_date=None,
    end_date=None,
    total_goal=None,
):
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
    from finance.savings_interest import Growth

    growth = Growth(rows, start_date, total_goal)
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
    from finance.isa_forecast import Headroom, is_isa

    headroom = Headroom(isa_limits)
    by_id = {row["id"]: row for row in rows}
    scheduled = [
        (event, by_id[event["savings_account"]])
        for event in automatic_events
        if event.get("savings_account") in by_id
    ]
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
        if end_date is not None and on > end_date:
            continue
        growth.advance(on)
        if kind == 0:
            row = by_id.get(period["savings_account"])
            if row is None or row["projected"] is None:
                continue
            part = period["amount"]
            cap = contribution_limit(row)
            if cap is not None:
                part = min(
                    part,
                    rounded(max(ZERO, cap - row["projected"]), rounding=ROUND_DOWN),
                )
            isa_room = headroom.room(row, on)
            if isa_room is not None:
                part = min(part, isa_room)
            headroom.use(row, on, part)
            row["projected"] += part
            row["added"] += part
            growth.check(on)
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
        fixed = period.get("account_allocations")
        if fixed is not None:
            if (
                not isinstance(fixed, dict)
                or sum((money(value, ZERO) for value in fixed.values()), ZERO) != amount
            ):
                raise ValueError(
                    "Planned account transfers must match the savings cash flow."
                )
            for row in rows:
                part = money(fixed.get(row["id"]), ZERO)
                if part <= ZERO or row["projected"] is None:
                    continue
                headroom.use(row, on, part)
                row["projected"] += part
                row["added"] += part
                if index == 0:
                    row["first"] += part
                assigned += part
                if (
                    row["target"]
                    and row["projected"] >= row["target"]
                    and row["goal_date"] is None
                ):
                    row["goal_date"] = on if period.get("funded", True) else None
        else:
            # Reserve room for already scheduled Premium Bonds payments. Their hard
            # holding cap applies even when a balance goal was set higher.
            room = {}
            for row in rows:
                if row["projected"] is None:
                    continue
                limit = contribution_limit(row)
                reserved_amount = sum(
                    (
                        event["amount"]
                        for event in automatic_events
                        if event.get("savings_account") == row["id"]
                        and event["date"] > on
                    ),
                    ZERO,
                )
                room[row["id"]] = (
                    rounded(
                        max(ZERO, limit - row["projected"] - reserved_amount),
                        rounding=ROUND_DOWN,
                    )
                    if limit is not None
                    else remaining
                )
            while remaining >= CENT:
                eligible = [
                    row
                    for row in rows
                    if row["projected"] is not None
                    and room.get(row["id"], ZERO) > ZERO
                    and (
                        headroom.room(row, on, scheduled) is None
                        or headroom.room(row, on, scheduled) > ZERO
                    )
                    and (not explicit or row["share"] > 0)
                ]
                fallback = False
                if not eligible and isa_limits is not None:
                    eligible = [
                        row
                        for row in rows
                        if row["projected"] is not None
                        and row["kind"] == "savings"
                        and not is_isa(row)
                        and not row.get("cash_reserve_limit")
                        and room.get(row["id"], ZERO) > ZERO
                    ]
                    fallback = bool(eligible)
                if not eligible:
                    break
                weights = sum(
                    (
                        row["share"] if explicit and not fallback else Decimal(1)
                        for row in eligible
                    ),
                    ZERO,
                )
                available = remaining
                isa_weights = sum(
                    (
                        row["share"] if explicit and not fallback else Decimal(1)
                        for row in eligible
                        if is_isa(row)
                    ),
                    ZERO,
                )
                shared_room = headroom.shared_room(on, scheduled)
                isa_budget = (
                    min(available * isa_weights / weights, shared_room)
                    if shared_room is not None and isa_weights
                    else None
                )
                cash_weights = sum(
                    (
                        row["share"] if explicit and not fallback else Decimal(1)
                        for row in eligible
                        if row["type"] == "cash_isa"
                    ),
                    ZERO,
                )
                cash_budget = (
                    min(
                        isa_budget * cash_weights / isa_weights,
                        headroom.cash_room(on, scheduled),
                    )
                    if isa_budget is not None and cash_weights
                    else None
                )
                progressed = ZERO
                for row in eligible:
                    weight = row["share"] if explicit and not fallback else Decimal(1)
                    part = rounded(
                        cash_budget * weight / cash_weights
                        if cash_budget is not None and row["type"] == "cash_isa"
                        else isa_budget * weight / isa_weights
                        if isa_budget is not None and is_isa(row)
                        else available * weight / weights,
                        rounding=ROUND_DOWN,
                    )
                    isa_room = headroom.room(row, on, scheduled)
                    if isa_room is not None and isa_room <= ZERO:
                        continue
                    part = min(
                        part,
                        room[row["id"]],
                        isa_room if isa_room is not None else part,
                    )
                    if not part and remaining >= CENT:
                        part = min(
                            CENT,
                            room[row["id"]],
                            isa_room if isa_room is not None else CENT,
                        )
                    part = min(part, remaining)
                    headroom.use(row, on, part)
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
        growth.check(on)
    if end_date is not None:
        growth.advance(end_date)
    growth.finish()
    return {
        "goal_date": growth.goal_date,
        "estimated_interest": sum((row["estimated_interest"] for row in rows), ZERO),
        "accounts": rows,
        "isa_years": headroom.years,
        "unallocated": unallocated,
        "current_total": sum(
            (row["balance"] for row in rows if row["balance"] is not None), ZERO
        ),
        "projected_total": sum(
            (row["projected"] for row in rows if row["projected"] is not None), ZERO
        ),
        "complete": all(row["balance"] is not None for row in rows),
    }
