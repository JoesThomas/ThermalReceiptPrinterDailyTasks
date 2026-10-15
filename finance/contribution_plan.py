"""Explain and compare a scheduled contribution without changing live payments."""

from decimal import Decimal, ROUND_DOWN
from finance.money import format_pounds, rounded
from finance.scenario_plan import build_validated
from finance.savings_targets import is_hargreaves

ZERO = Decimal(0)


def target_date(row, today):
    value = row["goal_date"] or row.get("extended_goal_date")
    return today if value == "already" else value


def time_to_target(reached, today):
    if reached is None:
        return "No funded date"
    if reached <= today:
        return "Now"
    months = (
        (reached.year - today.year) * 12
        + reached.month
        - today.month
        + (reached.day > today.day)
    )
    return f"About {months} " + ("month" if months == 1 else "months")


def contribution_plan(projection, current, today):
    inputs = current["inputs"]
    if not inputs["use_accounts"]:
        return {
            "available": False,
            "message": "Enable recorded accounts to compare a Hargreaves Lansdown contribution.",
        }
    events = [
        event
        for event in current["projection"]["events"]
        if is_hargreaves(event["name"])
        and event.get("savings_account")
        and not event.get("scenario_expense")
    ]
    identifiers = {event["savings_account"] for event in events}
    identifier = inputs.get("hl_account")
    if not identifier and len(identifiers) == 1:
        identifier = next(iter(identifiers))
    row = next(
        (row for row in current["account_plan"]["accounts"] if row["id"] == identifier),
        None,
    )
    if row is None or identifier not in identifiers:
        return {
            "available": False,
            "message": "Choose the account receiving the scheduled Hargreaves Lansdown payment. Ambiguous payments need a destination below.",
        }
    events = [event for event in events if event["savings_account"] == identifier]
    periods = current["forecast"]["payments"]
    scheduled = [
        sum(
            (
                event["amount"]
                for event in events
                if period["date"] <= event["date"] <= period["end"]
            ),
            ZERO,
        )
        for period in periods
    ]
    existing = next((amount for amount in scheduled if amount > ZERO), ZERO)
    if not existing:
        return {
            "available": False,
            "message": "No scheduled Hargreaves Lansdown payment occurs in this forecast.",
        }
    eligible = [
        allocation["income"]
        for period, allocation in zip(periods, row["allocations"])
        if period["salary"] > ZERO
        and period["funded"]
        and (inputs["strategy"] != "amex_first" or period["opening_card"] == ZERO)
    ]
    suggested = (
        existing + rounded(sum(eligible, ZERO) / len(eligible), rounding=ROUND_DOWN)
        if eligible
        else existing
    )
    proposed = inputs["hl_monthly"] if inputs["hl_monthly"] is not None else suggested
    alternative = (
        current
        if proposed == existing
        and all(amount in (ZERO, existing) for amount in scheduled)
        else build_validated(
            projection,
            inputs,
            today,
            regular_override={
                "account": identifier,
                "amount": proposed,
                "payment_names": {event["name"] for event in events},
            },
        )
    )
    alternative_row = next(
        account
        for account in alternative["account_plan"]["accounts"]
        if account["id"] == identifier
    )
    first = row["allocations"][0]
    first_income = (
        first["income"]
        if periods[0]["salary"] > ZERO and periods[0]["funded"]
        else ZERO
    )
    one_off = first["total"] - first_income
    goal = target_date(row, today)
    alternative_goal = target_date(alternative_row, today)
    return {
        "available": True,
        "account": row.get("label", row["name"]),
        "account_id": identifier,
        "existing": format_pounds(existing),
        "scheduled_this_period": format_pounds(scheduled[0]),
        "income_extra_this_period": format_pounds(first_income),
        "one_off_this_period": format_pounds(one_off),
        "total_this_period": format_pounds(scheduled[0] + first["total"]),
        "suggested": format_pounds(suggested),
        "proposed": format_pounds(proposed),
        "time_keep": time_to_target(goal, today),
        "time_proposed": time_to_target(alternative_goal, today),
        "goal_keep": goal.isoformat() if goal else None,
        "goal_proposed": alternative_goal.isoformat() if alternative_goal else None,
        "projected_keep": format_pounds(row["projected"]),
        "projected_proposed": format_pounds(alternative_row["projected"]),
        "minimum_bank": format_pounds(alternative["forecast"]["minimum_bank"]),
        "reserves_hold": alternative["forecast"]["run_out"] is None,
        "amex_keep": current["forecast"]["payoff"].isoformat()
        if current["forecast"]["payoff"]
        else None,
        "amex_proposed": alternative["forecast"]["payoff"].isoformat()
        if alternative["forecast"]["payoff"]
        else None,
        "periods": [
            {
                "date": period["date"].isoformat(),
                "scheduled": format_pounds(
                    sum(
                        (
                            event["amount"]
                            for event in alternative["forecast"]["events"]
                            if event.get("savings_account") == identifier
                            and period["date"] <= event["date"] <= period["end"]
                        ),
                        ZERO,
                    )
                ),
            }
            for period in alternative["forecast"]["payments"]
        ],
        "message": "The suggestion averages income-funded extras on eligible salary paydays; it excludes spare bank cash. Increases wait for Amex clearance under Amex first and are capped by period surplus and protected reserves. Existing scheduled payments continue without salary. The compared amount includes the scheduled payment and replaces part of the extra allocation; it is not added twice. This comparison changes no live payment.",
    }
