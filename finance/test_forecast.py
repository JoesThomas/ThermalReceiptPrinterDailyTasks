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
    result = _simulate(base, inputs, today)
    # Do not recommend accelerating debt while this pathway runs out of protected cash.
    if result['run_out'] and result.get('early_payoffs'):
        result = _simulate(base, dict(inputs, early_payoff=False), today)
        result['early_payoff_warning'] = 'Early settlements withheld: the selected pathway breaches protected reserves. Review income and costs.'
    return result


def _simulate(base, inputs, today):
    end = occurs(inputs["start"], inputs["months"])
    base = (
        dict(base, events=deepcopy(base["events"]))
        if inputs.get("regular_override") or inputs.get("use_accounts") or inputs.get("early_payoff")
        else base
    )
    from finance.early_payoff import prepare, settle, summary
    instalments = prepare(base, inputs, today)
    instalments_by_id = {row['id']: row for row in instalments}
    early_payoffs = []
    early_total = ZERO
    from finance.repayment_priority import free_cash, topup as fund_cash, period_targets
    priority = base.get('repayment_priority')
    previous_monzo = base.get('monzo_balance', ZERO)
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
    from finance.savings_interest import Growth

    growing_rows = deepcopy(accounts) if inputs.get("use_accounts") else []
    growth = Growth(growing_rows, today)
    growing_by_id = {row["id"]: row for row in growing_rows}
    has_interest = bool(growth.factors)
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
    from finance.necessities_budget import recorded_overdraft, limited_daily
    starting_overdraft = recorded_overdraft(base)
    daily = limited_daily(daily, inputs, (occurs(today, 1) - today).days,
                          owed=known and balance > ZERO, overdrawn=starting_overdraft or base['cash'] < ZERO)
    topup = base.get("cash_topup")
    for offset in range((end - today).days):
        on = today + timedelta(days=offset)
        if has_interest:
            growth.advance(on)
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
            normal_daily = max(
                ZERO,
                daily_base
                + inputs.get("spending_adjustment", ZERO)
                / Decimal((next_pay - on).days),
            )
            overdrawn = cash + base['buffer'] - reserved_total < ZERO or (month == 0 and starting_overdraft)
            daily = limited_daily(normal_daily, inputs, (next_pay - on).days,
                                  owed=known and balance > ZERO, overdrawn=overdrawn)
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
            would_overdraw = free_cash(cash, priority, reserved_total) - costs - normal_daily * (next_pay - on).days < ZERO
            daily = limited_daily(normal_daily, inputs, (next_pay - on).days,
                                  owed=known and balance > ZERO, overdrawn=overdrawn or would_overdraw)
            variable = daily * (next_pay - on).days
            protected_later = sum((e['amount'] if e.get('amex_statement_protection') else e.get('cash_fund_reserved', ZERO)
                                   for e in base['events'] if e['date'] >= next_pay), ZERO)
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
                                min(income - costs - variable, cash - costs - variable - protected_later),
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
                    start_date=today,
                    end_date=on,
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
                            event["amount"],
                            rounded(
                                max(ZERO, maximum - projected[key]), rounding=ROUND_DOWN
                            ),
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
            income_budget = rounded(max(ZERO, min(surplus, cash - costs - variable - protected_later)))
            use_spare_cash = inputs.get("invest_spare_cash") and salary > 0
            budget = (
                rounded(max(ZERO, cash - costs - variable - protected_later), rounding=ROUND_DOWN)
                if use_spare_cash
                else income_budget
            )
            ordinary_budget = budget
            if priority:
                income_budget = rounded(max(ZERO, min(surplus, free_cash(cash, priority, reserved_total) - costs - variable - protected_later)), rounding=ROUND_DOWN)
                budget = rounded(max(ZERO, free_cash(cash, priority, reserved_total) - costs - variable - protected_later), rounding=ROUND_DOWN)
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
            cash_added = ZERO
            if priority:
                # Future scheduled card money is already held in costs/protected_later.
                card_uncovered = max(ZERO, balance - scheduled - extra) if known else Decimal('Infinity')
                if rate and balance > extra:
                    card_uncovered = balance - extra
                cash_event = fund_cash(cash - extra - costs - variable - protected_later, priority,
                                       reserved_total, card_uncovered, topup, on) if topup or not inputs.get('use_accounts') else None
                if cash_event:
                    cash_added = cash_event['amount']
                    reserved_total += cash_added
                    reserve_transfers.append(cash_event)
                    if has_interest and cash_event.get('savings_account') in growing_by_id:
                        growing_by_id[cash_event['savings_account']]['projected'] += cash_added
                # Reserve goals must be fully funded before instalment extras or investments.
                general_room = max(ZERO, ordinary_budget - extra) if known and card_uncovered <= CENT else ZERO
                budget = extra + general_room
            else:
                general_room = budget - extra
            available = general_room
            settlements, replaced, settled = settle(instalments, on, current_events, available, run_out is None)
            early_extra = settled - replaced
            early_payoffs.extend(settlements)
            early_total += settled
            costs -= replaced
            surplus += replaced
            # A full settlement includes this period's already-reserved instalments.
            cash -= settled
            available -= early_extra
            saving = (
                available
                if inputs["save_all"]
                else min(available, max(ZERO, inputs["savings"] - automatic))
            )
            if strategy == "savings_first":
                extra = min(available - saving, debt_budget)
            balance = max(ZERO, balance - extra)
            cash -= extra + saving
            income_savings = min(saving, max(ZERO, income_budget - extra - early_extra))
            cash_repaid = max(ZERO, extra - income_budget)
            remaining_cash = (
                rounded(max(ZERO, cash - costs - variable - protected_later), rounding=ROUND_DOWN)
                if use_spare_cash and (not priority or (known and card_uncovered <= CENT))
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
                if topup and not priority:
                    scheduled_savings.append(topup)
                if priority:
                    scheduled_savings.extend(reserve_transfers)
                allocation = allocate(
                    accounts,
                    planned,
                    scheduled_savings,
                    equal=inputs["equal_savings"],
                    isa_limits=inputs.get("isa_limits"),
                    start_date=today,
                    end_date=on,
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
                income_savings = min(accepted, income_savings, max(ZERO, income_budget - extra - early_extra))
            cash_invested = max(ZERO, saving + remaining_cash - income_savings)
            cash -= remaining_cash
            saving += remaining_cash
            cash_invested_total += cash_invested
            cash_repaid_total += cash_repaid
            if has_interest and account_allocations:
                for key, contribution in account_allocations.items():
                    growing_by_id[key]["projected"] += contribution
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
            target_status = period_targets(cash - costs - variable - protected_later, priority,
                                           reserved_total, cash_added, previous_monzo)
            if priority:
                previous_monzo = target_status['monzo']
                if not known or card_uncovered > CENT:
                    target_status['monzo_transfer'] = ZERO
            periods.append(
                dict(
                    funded=run_out is None,
                    reserve_targets=target_status,
                    date=on,
                    end=next_pay - timedelta(days=1),
                    salary=salary,
                    rent=inputs["other"],
                    opening=opening,
                    costs=costs,
                    instalment_payoffs=settlements,
                    instalment_settled=settled,
                    instalment_extra=early_extra,
                    instalment_cash=max(ZERO, early_extra - max(ZERO, income_budget - extra)),
                    instalment_replaced=replaced,
                    variable=variable,
                    daily_spend=daily,
                    spending_limited=daily < normal_daily,
                    spending_cap=inputs.get('debt_spending_cap'),
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
                    cash_topups_total=reserved_total,
                    essentials_cash_after=free_cash(cash - costs - variable, priority, reserved_total),
                )
            )
        for event in events.get(on, []):
            amount = event["amount"]
            instalment = instalments_by_id.get(event.get('instalment_plan'))
            if instalment:
                amount = min(amount, instalment['remaining'])
                instalment['remaining'] -= amount
            growing_account = growing_by_id.get(event.get("savings_account"))
            if (
                has_interest
                and growing_account is not None
                and growing_account["projected"] is not None
            ):
                maximum = contribution_limit(growing_account)
                if maximum is not None:
                    amount = min(
                        amount,
                        rounded(
                            max(ZERO, maximum - growing_account["projected"]),
                            rounding=ROUND_DOWN,
                        ),
                    )
                    if amount < event["amount"]:
                        capped_savings_events = True
                        if periods:
                            periods[-1]["costs"] -= event["amount"] - amount
                            periods[-1]["automatic_savings"] -= event["amount"] - amount
                            periods[-1]["surplus"] += event["amount"] - amount
                            periods[-1]["cash_after_allocation"] += (
                                event["amount"] - amount
                            )
                growing_account["projected"] += amount
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
                        funded=run_out is None and free_cash(cash, priority, reserved_total) - daily >= 0,
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
                        and free_cash(cash, priority, reserved_total) - daily >= 0
                    ):
                        goal_date = on
        cash -= daily
        # Monthly spending adjustments can leave sub-penny Decimal division residue.
        if abs(cash) < Decimal("1e-18"):
            cash = ZERO
        if topup and not priority and on == topup["date"] and cash >= 0:
            # The gap was deducted in the starting protected buffer already.
            # Moving that reserved cash to the physical cash goal is one transfer.
            reserved_total = topup["amount"]
            if has_interest:
                growing_by_id[topup["savings_account"]]["projected"] += reserved_total
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
        if abs(bank) < Decimal("1e-18"):
            bank = ZERO
        if minimum_bank is None or bank < minimum_bank:
            minimum_bank = bank
            minimum_date = on
        available_cash = free_cash(cash, priority, reserved_total)
        if abs(available_cash) < Decimal("1e-18"):
            available_cash = ZERO
        minimum_cash = available_cash if minimum_cash is None else min(minimum_cash, available_cash)
        if periods:
            periods[-1]["closing_card"] = balance if known else None
        if available_cash < ZERO and run_out is None:
            run_out = on
        if offset % 7 == 0 or on == end - timedelta(days=1):
            points.append({"date": on, "scenario": cash})
        if on in checkpoint_dates:
            checkpoints.append((checkpoint_dates[on], cash))
    result = dict(
        reserve_targets_pending=max(ZERO, -cash) if priority else ZERO,
        priority_reserves=bool(priority),
        early_payoffs=early_payoffs,
        early_payoff_total=early_total,
        instalment_balances=summary(instalments),
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

    if inputs.get("use_accounts") and has_interest:
        from finance.savings_targets import allocate

        plan = allocate(
            accounts,
            periods,
            actual + reserve_transfers,
            equal=inputs["equal_savings"],
            isa_limits=inputs.get("isa_limits"),
            start_date=today,
            end_date=result["end"],
            total_goal=inputs["goal"],
        )
        result["account_plan"] = plan
        result["savings_end"] = plan["projected_total"]
        result["savings_interest"] = plan["estimated_interest"]
        if plan["estimated_interest"] and (
            run_out is None or (plan["goal_date"] and plan["goal_date"] < run_out)
        ):
            result["goal_date"] = plan["goal_date"]
    return result
