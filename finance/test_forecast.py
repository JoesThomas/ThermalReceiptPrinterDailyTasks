"""Daily scenario cash flow with payday allocation and finite card repayment."""

from bisect import bisect_right
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
from finance.projection import occurs
from finance.money import rounded
from copy import deepcopy

ZERO = Decimal(0)
CENT = Decimal("0.01")


def is_amex(name):
    key = "".join(c for c in str(name).lower() if c.isalnum())
    return "amex" in key or "americanexpress" in key


def is_card_payment(event):
    return not event.get("scenario_expense") and is_amex(event["name"])


def strategy_allows_increase(strategy, known, balance):
    return strategy != "amex_first" or (known and balance <= ZERO)


def simulate(base, inputs, today):
    end = occurs(inputs["start"], inputs["months"])
    base = (
        dict(base, events=deepcopy(base["events"]))
        if inputs.get("regular_override") or inputs.get("use_accounts")
        else base
    )
    accounts = base.get("savings_accounts", [])
    capped_savings_events = False
    if inputs.get("use_accounts"):
        from finance.isa_forecast import Headroom

        scheduled_headroom = Headroom(inputs.get("isa_limits"))
        account_by_id = {row["id"]: row for row in accounts}
        # Scheduled bond payments cannot take projected holdings over £50,000.
        from finance.savings_targets import contribution_limit

        bond_room = {
            row["id"]: max(ZERO, contribution_limit(row) - row["balance"])
            for row in accounts
            if contribution_limit(row) is not None and row["balance"] is not None
        }
        for event in sorted(base["events"], key=lambda row: row["date"]):
            requested_amount = event["amount"]
            key = event.get("savings_account")
            if key in account_by_id and today <= event["date"] < end:
                row = account_by_id[key]
                isa_room = scheduled_headroom.room(row, event["date"])
                if isa_room is not None:
                    event["amount"] = min(event["amount"], isa_room)
            if key in bond_room and today <= event["date"] < end:
                event["amount"] = min(event["amount"], bond_room[key])
                bond_room[key] -= event["amount"]
            if key in account_by_id and today <= event["date"] < end:
                scheduled_headroom.use(
                    account_by_id[key], event["date"], event["amount"]
                )
            if event["amount"] < requested_amount:
                capped_savings_events = True
    daily = base.get("daily_cost", base["daily"])
    salary_amount = inputs["salary"] + inputs["existing"]
    daily_base = daily
    minimum_bank = None
    minimum_cash = None
    minimum_date = None
    card = base.get("amex") or {}
    balance = card.get("balance")
    known = balance is not None
    balance = balance or ZERO
    apr = inputs["apr"] if inputs["apr"] is not None else card.get("apr")
    rate = (apr or ZERO) / Decimal(100) / Decimal(365)
    cash = base["cash"] - base["buffer"]
    events = {}
    for event in base["events"]:
        events.setdefault(event["date"], []).append(event)
    paydays = {
        occurs(inputs["start"], month): month for month in range(inputs["months"])
    }
    payday_dates = sorted(paydays)
    period_events = {on: [] for on in payday_dates}
    for event in base["events"]:
        index = bisect_right(payday_dates, event["date"]) - 1
        if index >= 0 and event["date"] < end:
            period_events[payday_dates[index]].append(event)
    checkpoint_dates = {
        occurs(inputs["start"], months) - timedelta(days=1): months
        for months in (1, 3, 6, 12, 24, 36, 48, 60)
        if months <= inputs["months"]
    }
    periods = []
    points = []
    actual = []
    transfers = ZERO
    extra_total = ZERO
    run_out = None
    payoff = None
    goal_date = (
        today
        if inputs["goal"] and inputs["starting_savings"] >= inputs["goal"]
        else None
    )
    interest_total = ZERO
    checkpoints = []
    automatic_total = ZERO
    cash_invested_total = ZERO
    cash_repaid_total = ZERO
    reserve_transfers = []
    reserved_total = ZERO
    topup = base.get("cash_topup")
    for offset in range((end - today).days):
        on = today + timedelta(days=offset)
        if known and balance > 0 and offset:
            interest = balance * rate
            balance += interest
            interest_total += interest
        if on in paydays:
            month = paydays[on]
            next_pay = occurs(inputs["start"], month + 1)
            salary_active = (
                (not inputs.get("salary_start") or on >= inputs["salary_start"])
                and (not inputs.get("salary_end") or on <= inputs["salary_end"])
                and on not in inputs.get("missed_salary_dates", [])
            )
            salary = salary_amount if salary_active else ZERO
            income = salary + inputs["other"]
            daily = max(
                ZERO,
                daily_base
                + inputs.get("spending_adjustment", ZERO)
                / Decimal((next_pay - on).days),
            )
            cash += income + (inputs["lump"] if month == 0 else ZERO)
            opening = cash + base["buffer"]
            current_events = period_events[on]
            noncard = sum(
                (e["amount"] for e in current_events if not is_card_payment(e)), ZERO
            )
            scheduled = sum(
                (e["amount"] for e in current_events if is_card_payment(e)), ZERO
            )
            if known:
                scheduled = min(
                    scheduled, balance + balance * rate * (next_pay - on).days
                )
            costs = noncard + scheduled
            variable = daily * (next_pay - on).days
            override = inputs.get("regular_override")
            if override and salary > 0:
                linked = [
                    event
                    for event in current_events
                    if event.get("savings_account") == override["account"]
                    and event["name"] in override["payment_names"]
                ]
                original = sum((event["amount"] for event in linked), ZERO)
                if linked and original > 0:
                    desired = override["amount"]
                    if desired > original:
                        # A regular increase uses salary surplus, never spare bank cash.
                        # Amex-first waits until the debt is cleared at the start of a period.
                        eligible = strategy_allows_increase(
                            inputs["strategy"], known, balance
                        )
                        room = (
                            max(
                                ZERO,
                                min(income - costs - variable, cash - costs - variable),
                            )
                            if eligible
                            else ZERO
                        )
                        desired = original + min(
                            desired - original, rounded(room, rounding=ROUND_DOWN)
                        )
                    remainder = desired
                    for index, event in enumerate(linked):
                        part = (
                            remainder
                            if index == len(linked) - 1
                            else rounded(
                                desired * event["amount"] / original,
                                rounding=ROUND_DOWN,
                            )
                        )
                        event["amount"] = part
                        remainder -= part
                    costs += desired - original
            if inputs.get("use_accounts") and current_events:
                from finance.savings_targets import allocate, contribution_limit
                from finance.isa_forecast import Headroom

                previous = allocate(
                    accounts,
                    periods,
                    actual + reserve_transfers,
                    equal=inputs["equal_savings"],
                    isa_limits=inputs.get("isa_limits"),
                )
                caps = Headroom(previous["isa_years"])
                projected = {
                    row["id"]: row["projected"] for row in previous["accounts"]
                }
                for event in sorted(current_events, key=lambda row: row["date"]):
                    key = event.get("savings_account")
                    if key not in account_by_id:
                        continue
                    row = account_by_id[key]
                    original = event["amount"]
                    room = caps.room(row, event["date"])
                    if room is not None:
                        event["amount"] = min(event["amount"], room)
                    maximum = contribution_limit(row)
                    if maximum is not None and projected[key] is not None:
                        event["amount"] = min(
                            event["amount"], max(ZERO, maximum - projected[key])
                        )
                    caps.use(row, event["date"], event["amount"])
                    if projected[key] is not None:
                        projected[key] += event["amount"]
                    costs += event["amount"] - original
                    if event["amount"] < original:
                        capped_savings_events = True
            automatic = sum(
                (e["amount"] for e in current_events if e.get("savings_account")), ZERO
            )
            surplus = income - costs - variable
            income_budget = rounded(max(ZERO, min(surplus, cash - costs - variable)))
            use_spare_cash = inputs.get("invest_spare_cash") and salary > 0
            budget = (
                rounded(max(ZERO, cash - costs - variable), rounding=ROUND_DOWN)
                if use_spare_cash
                else income_budget
            )
            opening_card = balance if known else None
            debt_budget = (
                max(ZERO, balance - scheduled)
                if known and not card.get("full_reserved")
                else ZERO
            )
            strategy = inputs["strategy"]
            if strategy == "amex_first":
                extra = min(budget, debt_budget)
            elif strategy == "split":
                extra = rounded(min(budget * inputs["split"] / 100, debt_budget))
            else:
                extra = ZERO
            available = budget - extra
            saving = (
                available
                if inputs["save_all"]
                else min(available, max(ZERO, inputs["savings"] - automatic))
            )
            if strategy == "savings_first":
                extra = min(budget - saving, debt_budget)
            balance = max(ZERO, balance - extra)
            cash -= extra + saving
            income_savings = min(saving, max(ZERO, income_budget - extra))
            cash_repaid = max(ZERO, extra - income_budget)
            remaining_cash = (
                rounded(max(ZERO, cash - costs - variable), rounding=ROUND_DOWN)
                if use_spare_cash
                else ZERO
            )
            proposed = saving + remaining_cash
            savings_budget = proposed
            retained = ZERO
            account_allocations = None
            if inputs.get("use_accounts"):
                from finance.savings_targets import allocate

                planned = [
                    dict(p, savings_budget=p.get("savings_budget", p["savings"]))
                    for p in periods
                ]
                planned.append(
                    dict(
                        date=on,
                        end=next_pay - timedelta(days=1),
                        savings=proposed,
                        income_savings=income_savings,
                        funded=run_out is None,
                    )
                )
                scheduled_savings = [
                    e
                    for e in base["events"]
                    if today <= e["date"] < end and e.get("savings_account")
                ]
                if topup:
                    scheduled_savings.append(topup)
                allocation = allocate(
                    accounts,
                    planned,
                    scheduled_savings,
                    equal=inputs["equal_savings"],
                    isa_limits=inputs.get("isa_limits"),
                )
                accepted = sum(
                    (
                        row["allocations"][-1]["total"]
                        for row in allocation["accounts"]
                        if row["allocations"]
                    ),
                    ZERO,
                )
                account_allocations = {
                    row["id"]: row["allocations"][-1]["total"]
                    for row in allocation["accounts"]
                    if row["allocations"]
                }
                retained = proposed - accepted
                # Restore money that has no eligible destination to bank cash.
                cash += retained
                if strategy == "savings_first":
                    redirected = min(retained, max(ZERO, debt_budget - extra))
                    extra += redirected
                    balance = max(ZERO, balance - redirected)
                    cash -= redirected
                    retained -= redirected
                    cash_repaid = max(ZERO, extra - income_budget)
                saving = accepted - remaining_cash
                income_savings = min(accepted, income_savings)
            cash_invested = max(ZERO, saving + remaining_cash - income_savings)
            cash -= remaining_cash
            saving += remaining_cash
            cash_invested_total += cash_invested
            cash_repaid_total += cash_repaid
            transfers += saving
            extra_total += extra
            if (
                known
                and balance <= CENT
                and payoff is None
                and card.get("balance", ZERO) > 0
            ):
                payoff = on
                balance = ZERO
            if (
                inputs["goal"]
                and goal_date is None
                and inputs["starting_savings"]
                + transfers
                + automatic_total
                + reserved_total
                >= inputs["goal"]
                and run_out is None
            ):
                goal_date = on
            periods.append(
                dict(
                    funded=run_out is None,
                    date=on,
                    end=next_pay - timedelta(days=1),
                    salary=salary,
                    rent=inputs["other"],
                    opening=opening,
                    costs=costs,
                    variable=variable,
                    surplus=surplus,
                    budget=budget,
                    income_budget=income_budget,
                    cash_repaid=cash_repaid,
                    savings=saving,
                    savings_budget=savings_budget,
                    account_allocations=account_allocations,
                    retained_in_bank=retained,
                    income_savings=income_savings,
                    cash_invested=cash_invested,
                    automatic_savings=automatic,
                    extra=extra,
                    planned_card=scheduled,
                    opening_card=opening_card,
                    balance_after_extra=balance,
                    savings_total=transfers,
                    cash_after_allocation=cash - costs - variable,
                )
            )
        for event in events.get(on, []):
            amount = event["amount"]
            if known and is_card_payment(event):
                amount = min(amount, balance)
                balance -= amount
                if balance <= CENT and payoff is None and card.get("balance", ZERO) > 0:
                    payoff = on
                    balance = ZERO
            if amount > 0:
                cash -= amount
                actual.append(
                    dict(
                        event,
                        amount=amount,
                        funded=run_out is None and cash - daily >= 0,
                    )
                )
                if event.get("savings_account"):
                    automatic_total += amount
                    if (
                        inputs["goal"]
                        and goal_date is None
                        and inputs["starting_savings"]
                        + transfers
                        + automatic_total
                        + reserved_total
                        >= inputs["goal"]
                        and run_out is None
                        and cash - daily >= 0
                    ):
                        goal_date = on
        cash -= daily
        # Monthly spending adjustments can leave sub-penny Decimal division residue.
        if abs(cash) < Decimal("1e-18"):
            cash = ZERO
        if topup and on == topup["date"] and cash >= 0:
            # The gap was deducted in the starting protected buffer already.
            # Moving that reserved cash to the physical cash goal is one transfer.
            reserved_total = topup["amount"]
            reserve_transfers.append(dict(topup, funded=True))
            if (
                inputs["goal"]
                and goal_date is None
                and inputs["starting_savings"]
                + transfers
                + automatic_total
                + reserved_total
                >= inputs["goal"]
                and run_out is None
            ):
                goal_date = on
        bank = cash + base["buffer"] - reserved_total
        if minimum_bank is None or bank < minimum_bank:
            minimum_bank = bank
            minimum_date = on
        minimum_cash = cash if minimum_cash is None else min(minimum_cash, cash)
        if periods:
            periods[-1]["closing_card"] = balance if known else None
        if cash < 0 and run_out is None:
            run_out = on
        if offset % 7 == 0 or on == end - timedelta(days=1):
            points.append({"date": on, "scenario": cash})
        if on in checkpoint_dates:
            checkpoints.append((checkpoint_dates[on], cash))
    return dict(
        capped_savings_events=capped_savings_events,
        minimum_bank=minimum_bank,
        minimum_cash=minimum_cash,
        minimum_date=minimum_date,
        valid=True,
        end=end - timedelta(days=1),
        end_cash=cash,
        run_out=run_out,
        payments=periods,
        points=points,
        checkpoints=checkpoints,
        events=actual,
        savings_total=transfers,
        cash_invested_total=cash_invested_total,
        cash_repaid_total=cash_repaid_total,
        extra_total=extra_total,
        card_end=balance if known else None,
        payoff=payoff,
        apr=apr,
        interest=interest_total,
        goal_date=goal_date,
        automatic_total=automatic_total,
        reserved_total=reserved_total,
        reserve_transfers=reserve_transfers,
        savings_end=inputs["starting_savings"]
        + transfers
        + automatic_total
        + reserved_total,
    )
