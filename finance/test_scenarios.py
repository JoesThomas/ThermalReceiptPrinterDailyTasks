"""Read-only spending comparisons and serializable forecast details."""

from datetime import date
from decimal import Decimal
from finance.scenario_plan import build, build_validated
from finance.money import format_pounds as pounds
from finance.contribution_plan import contribution_plan

ZERO = Decimal(0)


def goal_date(value, today):
    if value == "already":
        return today
    return value if isinstance(value, date) else None


def snapshot(result, today):
    forecast = result["forecast"]
    inputs = result["inputs"]
    accounts = []
    for row in result["account_plan"]["accounts"] if inputs["use_accounts"] else []:
        reached = goal_date(row["goal_date"] or row.get("extended_goal_date"), today)
        accounts.append(
            {
                "name": row.get("label", row["name"]),
                "balance": pounds(row["balance"]),
                "target": pounds(row["target"]),
                "projected": pounds(row["projected"]),
                "goal_date": reached.isoformat() if reached else None,
                "extended": bool(reached and reached > forecast["end"]),
                "reached": bool(row["goal_date"]),
            }
        )
    reached = forecast["goal_date"] or forecast.get("extended_goal_date")
    return {
        "end": forecast["end"].isoformat(),
        "payoff": forecast["payoff"].isoformat() if forecast["payoff"] else None,
        "amex_end": pounds(forecast["card_end"]),
        "savings_end": pounds(forecast["savings_end"]),
        "minimum_bank": pounds(forecast["minimum_bank"]),
        "minimum_date": forecast["minimum_date"].isoformat(),
        "reserve_goals_after_amex": bool(result["projection"].get("repayment_priority")),
        "reserve_targets_pending": pounds(forecast.get('reserve_targets_pending', ZERO)),
        "bank_reserve": pounds(
            result["projection"]["buffer"]
            - (result["projection"].get("reserve_details") or {}).get("gap", ZERO)
            - (result["projection"].get("reserve_details") or {}).get(
                "tax_reserve", ZERO
            )
        ),
        "reserves_hold": forecast["run_out"] is None,
        "shortfall_date": forecast["run_out"].isoformat()
        if forecast["run_out"]
        else None,
        "goal_date": reached.isoformat() if reached else None,
        "goal_extended": bool(reached and reached > forecast["end"]),
        "has_goal": bool(inputs["goal"]),
        "accounts": accounts,
        "periods": [
            {
                "date": p["date"].isoformat(),
                "salary": pounds(p["salary"]),
                "costs": pounds(p["costs"]),
                "spending": pounds(p["variable"]),
                "extra": pounds(p["extra"]),
                "instalments": pounds(p.get("instalment_settled", ZERO)),
                "savings": pounds(p["savings"]),
                "automatic": pounds(p["automatic_savings"]),
            }
            for p in forecast["payments"]
        ],
        "checkpoints": [
            {"months": months, "cash": pounds(cash)}
            for months, cash in result["checkpoints"]
        ],
    }


def compare(projection, values, today, *, current=None):
    current = current or build(projection, values, today)
    difference = current["inputs"]["comparison_spend"]
    cases = {ZERO: current}

    def case(adjustment):
        if adjustment not in cases:
            cases[adjustment] = build_validated(
                projection, current["inputs"], today, spending_adjustment=adjustment
            )
        return cases[adjustment]

    lower = case(-difference)
    higher = case(difference)
    sensitivity = case(Decimal(-100))
    changes = []
    for row, other in zip(
        current["account_plan"]["accounts"], sensitivity["account_plan"]["accounts"]
    ):
        original = goal_date(row["goal_date"] or row.get("extended_goal_date"), today)
        improved = goal_date(
            other["goal_date"] or other.get("extended_goal_date"), today
        )
        if not row["target"]:
            continue
        if original and improved:
            months = max(0, round((original - improved).days / 30.4375))
            message = (
                f"About {months} " + ("month" if months == 1 else "months") + " sooner"
                if months
                else "Same approximate timing"
            )
        elif improved:
            message = f"Funded goal date: {improved:%d %b %Y}"
        else:
            message = "No funded goal date within the planning horizon"
        changes.append({"name": row.get("label", row["name"]), "message": message})
    original = current["forecast"]["goal_date"] or current["forecast"].get(
        "extended_goal_date"
    )
    improved = sensitivity["forecast"]["goal_date"] or sensitivity["forecast"].get(
        "extended_goal_date"
    )
    goal_message = None
    if original and improved:
        months = max(0, round((original - improved).days / 30.4375))
        goal_message = (
            f"Overall goal about {months} "
            + ("month" if months == 1 else "months")
            + " sooner."
            if months
            else "Overall goal: same approximate timing."
        )
    delta = sensitivity["forecast"]["savings_end"] - current["forecast"]["savings_end"]
    amex_message = None
    if current["forecast"]["payoff"] and sensitivity["forecast"]["payoff"]:
        months = max(
            0,
            round(
                (current["forecast"]["payoff"] - sensitivity["forecast"]["payoff"]).days
                / 30.4375
            ),
        )
        amex_message = (
            f"Amex clears about {months} "
            + ("month" if months == 1 else "months")
            + " sooner"
            if months
            else "Amex: same approximate clearance timing"
        )
    from finance.transfer_explanation import explain
    from finance.visuals import test_charts

    stress = dict(
        current["inputs"],
        one_off_expenses=list(current["inputs"]["one_off_expenses"])
        + [
            dict(
                date=current["inputs"]["start"],
                amount=difference,
                name="Illustrative extra expense",
                scenario_expense=True,
            )
        ],
    )
    extra_cost = build_validated(projection, stress, today) if difference else current
    missed = dict(
        current["inputs"],
        missed_salary_dates=list(current["inputs"]["missed_salary_dates"])
        + [current["inputs"]["start"]],
    )
    late_salary = (
        build_validated(projection, missed, today)
        if current["forecast"]["payments"][0]["salary"]
        else current
    )
    chart_cases = [
        ("Current plan", current),
        ("Lower spending", lower),
        ("Higher spending", higher),
        ("Extra one-off expense", extra_cost),
        ("First salary missed", late_salary),
    ]
    return {
        "charts": test_charts(current, today, chart_cases),
        "stress_scenarios": [
            dict(snapshot(extra_cost, today), name="Extra one-off expense"),
            dict(snapshot(late_salary, today), name="First salary missed"),
        ],
        "stress_assumptions": [
            f"Extra expense: {pounds(difference)} on the first payday.",
            "First salary missed: salary resumes on the next scheduled payday; other income is unchanged.",
        ],
        "early_payoff": {
            "warning": current['forecast'].get('early_payoff_warning'),
            "plans": [dict(name=row['name'], remaining=pounds(row['remaining']),
                           date=row['settlement']['date'].isoformat() if row['settlement'] else None,
                           amount=pounds(row['settlement']['amount']) if row['settlement'] else None,
                           replaced=pounds(row['settlement']['scheduled_replaced']) if row['settlement'] else None)
                      for row in current['forecast'].get('instalment_balances', [])],
        } if current['inputs'].get('early_payoff') else None,
        "transfers": explain(current),
        "contribution": contribution_plan(projection, current, today),
        "scenarios": [
            dict(snapshot(result, today), name=name, adjustment=pounds(adjustment))
            for name, adjustment, result in [
                ("Lower spending", -difference, lower),
                ("Current plan", ZERO, current),
                ("Higher spending", difference, higher),
            ]
        ],
        "comparison_spend": pounds(difference),
        "sensitivity": {
            "savings_change": pounds(delta),
            "message": f"Up to £100/month less everyday spending: {pounds(delta)} more savings by forecast end.",
            "goal_message": goal_message,
            "amex_message": amex_message,
            "goals": changes,
        },
    }
