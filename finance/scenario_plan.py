"""Prepare an isolated finance snapshot and calculate scenario goals."""

from copy import deepcopy
from decimal import Decimal
from datetime import timedelta
from finance.projection import occurs, money
from finance.test_forecast import simulate
from finance.scenario_inputs import validate


def build(projection, values, today, *, spending_adjustment=Decimal(0)):
    return build_validated(
        projection,
        validate(values, today),
        today,
        spending_adjustment=spending_adjustment,
    )


def build_validated(
    projection, inputs, today, *, spending_adjustment=Decimal(0), regular_override=None
):
    inputs = dict(
        inputs,
        spending_adjustment=spending_adjustment,
        regular_override=regular_override,
    )
    if not projection.get("valid"):
        raise ValueError(
            "The finance forecast is incomplete. Refresh Finance review and confirm balances, repayment dates and a daily spending estimate first."
        )
    base = deepcopy(projection)
    reserve = base.get("reserve_details") or {}
    separate = money(reserve.get("gap"), Decimal(0)) + money(reserve.get("tax_reserve"), Decimal(0))
    base["buffer"] = max(base["buffer"], inputs.get("minimum_bank_balance", Decimal(0)) + separate)
    if inputs["invest_spare_cash"] and inputs["salary"] + inputs["existing"] > 0:
        reserve = base.get("reserve_details") or {}
        separate = money(reserve.get("gap"), Decimal(0)) + money(
            reserve.get("tax_reserve"), Decimal(0)
        )
        base["buffer"] = max(base["buffer"], Decimal(1000) + separate)
    if inputs.get("monzo_target"):
        reserve = base.get("reserve_details") or {}
        separate = money(reserve.get("gap"), Decimal(0)) + money(
            reserve.get("tax_reserve"), Decimal(0)
        )
        base["buffer"] = (
            max(base["buffer"], Decimal(1000) + separate) + inputs["monzo_target"]
        )
        base["monzo_target"] = inputs["monzo_target"]
        base["monzo_balance"] = (
            inputs["monzo_balance"]
            if inputs["monzo_balance"] is not None
            else base.get("monzo_balance", Decimal(0))
        )
        if base["monzo_balance"] > base["cash"]:
            raise ValueError(
                "Starting Monzo balance is part of combined bank cash and cannot exceed it."
            )
    base["events"].extend(inputs["one_off_expenses"])
    accounts = base.get("savings_accounts", [])
    from finance.savings_targets import (
        allocate,
        link_regular_savings,
        prepare_cash_topup,
    )

    if inputs["use_accounts"]:
        prepare_cash_topup(base, accounts, today, inputs["start"])
        inputs["starting_savings"] = sum(
            (row["balance"] for row in accounts if row["balance"] is not None),
            Decimal(0),
        )
        link_regular_savings(
            base["events"],
            [row for row in accounts if row["balance"] is not None],
            inputs.get("payment_accounts", {}),
        )
    from finance.repayment_priority import configure
    base['repayment_priority'] = configure(base, inputs)
    from finance.isa_forecast import allowance_snapshot

    isa_limits = (
        allowance_snapshot(
            accounts,
            today,
            base.get("isa_records"),
            over_65=inputs.get("isa_over_65", False),
        )
        if inputs.get("respect_isa_allowance") and inputs["use_accounts"]
        else None
    )
    inputs["isa_limits"] = isa_limits
    forecast = simulate(base, inputs, today)
    account_plan = forecast.get("account_plan") or allocate(
        accounts,
        forecast["payments"] if inputs["use_accounts"] else [],
        forecast["events"] + forecast["reserve_transfers"]
        if inputs["use_accounts"]
        else [],
        equal=inputs["equal_savings"],
        isa_limits=isa_limits,
    )
    if (
        inputs["goal"]
        and forecast["goal_date"] is None
        or inputs["use_accounts"]
        and any(
            row["target"] and row["goal_date"] is None
            for row in account_plan["accounts"]
        )
    ) and inputs["mode"] != "lump":
        extended_inputs = dict(inputs, months=60)
        while (occurs(inputs["start"], extended_inputs["months"]) - today).days > 1826:
            extended_inputs["months"] -= 1
        extended = (
            forecast
            if extended_inputs["months"] == inputs["months"]
            else simulate(base, extended_inputs, today)
        )
        forecast["extended_goal_date"] = extended["goal_date"]
        forecast["extended_goal_months"] = extended_inputs["months"]
        extended_accounts = extended.get("account_plan") or allocate(
            accounts,
            extended["payments"] if inputs["use_accounts"] else [],
            extended["events"] + extended["reserve_transfers"]
            if inputs["use_accounts"]
            else [],
            equal=inputs["equal_savings"],
            isa_limits=isa_limits,
        )
        for row, full in zip(account_plan["accounts"], extended_accounts["accounts"]):
            row["extended_goal_date"] = full["goal_date"]
            if not full["goal_date"] and inputs["use_accounts"]:
                from finance.long_term_goals import estimate
                row["estimated_goal_date"] = estimate(full, extended, extended_inputs)
    from finance.monthly_balances import build as month_end_balances
    forecast['monthly_balances'] = month_end_balances(base, inputs, forecast, account_plan, today)
    first = forecast["payments"][0]
    bills = [
        event
        for event in forecast["events"]
        if inputs["start"] <= event["date"] <= first["end"]
    ]
    if inputs["use_accounts"]:
        forecast["unallocated_savings"] = account_plan["unallocated"]
    else:
        forecast["unallocated_savings"] = forecast["savings_total"]
    return dict(
        account_plan=account_plan,
        checkpoints=forecast["checkpoints"],
        surplus=first["surplus"],
        monthly_savings=first["savings"],
        inputs=inputs,
        projection=base,
        forecast=forecast,
        bills=bills,
        bills_total=sum((e["amount"] for e in bills), Decimal(0)),
        variable=first["variable"],
        payday_cash=first["opening"],
        savings=first["savings"],
        spend=max(Decimal(0), first["cash_after_allocation"]),
        shortfall=max(Decimal(0), -first.get("essentials_cash_after", first["cash_after_allocation"])),
        cycle_end=first["end"],
    )
