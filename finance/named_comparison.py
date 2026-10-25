"""Compare two saved inputs using one common collection and explicit overrides."""

from finance.scenario_inputs import validate
from finance.scenario_plan import build
from finance.test_scenarios import snapshot
from finance.transfer_explanation import explain

LABELS = {
    "minimum_bank_balance": "Minimum bank balance",
    "limit_spending_when_owed": "Limit spending while owed/overdrawn",
    "debt_spending_cap": "Debt/overdraft spending maximum per month",
    "early_payoff": "Pay selected instalments off early",
    "salary": "Monthly salary",
    "other_income": "Other income",
    "strategy": "Repayment strategy",
    "start": "First payday",
    "months": "Forecast months",
    "opening_cash": "Starting bank cash",
    "daily_spend": "Daily spending",
    "amex_owed": "Amex balance override",
    "savings_target": "Monthly savings target",
    "use_saved_accounts": "Use recorded accounts",
    "equal_savings": "Split savings equally",
    "invest_spare_cash": "Use spare bank cash on salary paydays",
}


def compare(left, right, today, collect):
    rows = [left, right]
    for row in rows:
        try:
            validate(row["values"], today)
        except ValueError as error:
            raise ValueError(
                row["name"] + ": " + str(error) + " Load that scenario to update it."
            ) from None
    manual = all(
        row["values"].get("opening_cash", "").strip()
        and row["values"].get("daily_spend", "").strip()
        for row in rows
    )
    projections = collect([row["values"] for row in rows], today)
    results = []
    for row, base in zip(rows, projections):
        values = row["values"]
        result = build(base, values, today)
        results.append(
            dict(
                snapshot(result, today),
                name=row["name"],
                transfers=explain(result),
                warnings=base.get("warnings", []),
            )
        )
    account_names = {
        account["id"]: account["name"]
        for projection in projections
        for account in projection.get("savings_accounts", [])
    }
    from finance.early_payoff import options, PREFIX
    payoff_names = {PREFIX + row['id']: row['name'] for projection in projections
                    for row in options(projection.get('repayment_options', []))}
    money_fields = set(
        "salary existing_salary other_income lump_sum savings_target savings_goal starting_savings opening_cash daily_spend amex_owed debt_spending_cap".split()
    )

    def display(key, value):
        if key.startswith(PREFIX):
            return "Confirmed" if value == "on" else "Not selected"
        if key in {
            "early_payoff",
            "limit_spending_when_owed",
            "save_all",
            "invest_spare_cash",
            "equal_savings",
            "use_saved_accounts",
        }:
            return "Enabled" if value == "on" else "Disabled"
        if not value:
            return "Not set"
        if key in money_fields:
            from finance.money import format_pounds
            from finance.projection import money

            return format_pounds(money(value))
        if key == "strategy":
            return {
                "amex_first": "Amex first",
                "savings_first": "Savings first",
                "split": "Split",
            }[value]
        if key == "hl_account" or key.startswith("payment_account_"):
            return account_names.get(value, "Account unavailable; review destination")
        return value

    keys = sorted(set(left["values"]) | set(right["values"]))
    differences = [
        {
            "label": LABELS.get(
                key,
                ("Early payoff: " + payoff_names.get(key, "Plan unavailable; review selection")) if key.startswith(PREFIX) else key.replace("_", " ").replace(
                    "payment account ", "Scheduled destination "
                ),
            ),
            "left": display(key, left["values"].get(key, "")),
            "right": display(key, right["values"].get(key, "")),
        }
        for key in keys
        if left["values"].get(key, "") != right["values"].get(key, "")
    ]
    return {
        "results": results,
        "differences": differences,
        "manual": manual,
        "generated_on": today.isoformat(),
    }
