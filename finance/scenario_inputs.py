"""Validate manual forecast inputs without accessing finance records."""

from datetime import timedelta
from decimal import Decimal
from finance.projection import day, money, occurs


def validate(values, today):
    if values.get("receipt_detail", "compact") not in {"compact", "detailed"}:
        raise ValueError("Choose compact or detailed finance receipt.")
    monzo_target = money(values.get("monzo_target", "0") or "0")
    monzo_balance = (
        money(values["monzo_balance"])
        if values.get("monzo_balance", "").strip()
        else None
    )
    if (
        monzo_target is None
        or not 0 <= monzo_target <= 10000000
        or (monzo_balance is not None and not 0 <= monzo_balance <= 10000000)
        or (values.get("monzo_balance", "").strip() and monzo_balance is None)
    ):
        raise ValueError("Enter valid Monzo amounts.")
    goal = money(values.get("savings_goal", "0") or "0")
    starting_savings = money(values.get("starting_savings", "0") or "0")
    mode = values.get("mode", "replace")
    lump_mode = mode == "lump"
    lump = (
        money(values.get("lump_sum", "0") or "0")
        if mode in {"lump", "lump_income"}
        else Decimal(0)
    )
    salary = Decimal(0) if lump_mode else money(values.get("salary"))
    existing = (
        Decimal(0) if lump_mode else money(values.get("existing_salary", "0") or "0")
    )
    other = Decimal(0) if lump_mode else money(values.get("other_income", "0") or "0")
    savings = (
        Decimal(0) if lump_mode else money(values.get("savings_target", "0") or "0")
    )
    if any(
        v is None or v < 0 or v > 10000000
        for v in (salary, existing, other, savings, lump, goal, starting_savings)
    ):
        raise ValueError("Enter valid non-negative monthly amounts.")
    if mode not in {"replace", "additional", "lump", "lump_income"}:
        raise ValueError("Choose how the potential salary should be used.")
    strategy = values.get("strategy", "savings_first")
    if strategy not in {"savings_first", "amex_first", "split"}:
        raise ValueError("Choose a repayment strategy.")
    split = money(values.get("amex_split", "50") or "50")
    apr = money(values.get("amex_apr")) if values.get("amex_apr", "").strip() else None
    if (
        split is None
        or not 0 <= split <= 100
        or (values.get("amex_apr", "").strip() and (apr is None or not 0 <= apr <= 100))
    ):
        raise ValueError("Enter an Amex rate and split percentage between 0 and 100.")
    start = day(values.get("start"))
    if not start or not today <= start <= today + timedelta(days=365):
        raise ValueError("Choose a first payday between today and one year from today.")
    try:
        months = int(values.get("months", "12"))
    except (ValueError, TypeError):
        raise ValueError("Choose 1 to 60 forecast months.") from None
    if not 1 <= months <= 60 or (occurs(start, months) - today).days > 1826:
        raise ValueError("Choose a forecast ending within five years of today.")
    salary_start = (
        day(values.get("salary_start"))
        if values.get("salary_start", "").strip()
        else None
    )
    salary_end = (
        day(values.get("salary_end")) if values.get("salary_end", "").strip() else None
    )
    horizon = occurs(start, months) - timedelta(days=1)
    for field, parsed in [("salary_start", salary_start), ("salary_end", salary_end)]:
        if values.get(field, "").strip() and (
            parsed is None or not today <= parsed <= today + timedelta(days=1826)
        ):
            raise ValueError("Choose valid salary dates within five years of today.")
    if salary_start and salary_end and salary_end < salary_start:
        raise ValueError("Last salary date must not be before the first salary date.")
    skipped = []
    paydays = {occurs(start, month) for month in range(months)}
    for raw_date in values.get("missed_salary_dates", "").split(","):
        if not raw_date.strip():
            continue
        missed = day(raw_date.strip())
        if missed not in paydays:
            raise ValueError(
                "Skipped salary dates must be paydays within the selected forecast, separated by commas."
            )
        skipped.append(missed)
    difference = money(values.get("comparison_spend", "100") or "100")
    if difference is None or not 0 <= difference <= 100000:
        raise ValueError(
            "Choose a monthly spending comparison between £0 and £100,000."
        )
    expenses = []
    raw = values.get("one_off_expenses", "")
    if len(raw) > 10000:
        raise ValueError("Use at most 50 one-off expenses.")
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        on = day(parts[0]) if len(parts) == 3 else None
        cost = money(parts[1]) if len(parts) == 3 else None
        if (
            on is None
            or not today <= on <= horizon
            or cost is None
            or not 0 < cost <= 10000000
            or not parts[2]
            or len(parts[2]) > 90
            or any(ord(c) < 32 for c in parts[2])
        ):
            raise ValueError(
                "Use one expense per line: YYYY-MM-DD | amount | description. Dates must be inside the selected forecast."
            )
        expenses.append(
            {
                "date": on,
                "amount": cost,
                "name": parts[2],
                "category": "one_off",
                "scenario_expense": True,
            }
        )
    if len(expenses) > 50:
        raise ValueError("Use at most 50 one-off expenses.")
    regular = (
        money(values.get("hl_monthly"))
        if values.get("hl_monthly", "").strip()
        else None
    )
    if values.get("hl_monthly", "").strip() and (
        regular is None or not 0 <= regular <= 10000000
    ):
        raise ValueError(
            "Enter a non-negative Hargreaves Lansdown monthly contribution."
        )
    mappings = {
        key.removeprefix("payment_account_"): identifier
        for key, identifier in values.items()
        if key.startswith("payment_account_") and identifier
    }
    if any(
        not key.isalnum() or len(key) > 180 or len(identifier) > 90
        for key, identifier in mappings.items()
    ):
        raise ValueError("Choose valid scheduled savings destinations.")
    from finance.early_payoff import PREFIX
    payoff_plans = [key.removeprefix(PREFIX) for key, value in values.items()
                    if key.startswith(PREFIX) and value == 'on']
    import re
    if len(payoff_plans) > 50 or any(not re.fullmatch(r'[a-f0-9]{32}', key) for key in payoff_plans):
        raise ValueError('Choose valid instalment plans for early payoff.')
    early_payoff = values.get('early_payoff') == 'on'
    if early_payoff and not payoff_plans:
        raise ValueError('Select at least one instalment plan confirmed eligible for fee-free early payoff.')
    debt_spending_cap = money(values.get('debt_spending_cap', '700') or '700')
    if debt_spending_cap is None or not 0 < debt_spending_cap <= 100000:
        raise ValueError('Choose a monthly necessities spending maximum above £0 and up to £100,000.')
    return dict(
        limit_spending_when_owed=values.get('limit_spending_when_owed') == 'on',
        debt_spending_cap=debt_spending_cap,
        early_payoff=early_payoff,
        payoff_plans=payoff_plans,
        respect_isa_allowance=values.get("respect_isa_allowance") == "on"
        and values.get("use_saved_accounts") == "on",
        isa_over_65=values.get("isa_over_65") == "on",
        monzo_target=monzo_target,
        monzo_balance=monzo_balance,
        hl_monthly=regular,
        hl_account=values.get("hl_account", ""),
        payment_accounts=mappings,
        equal_savings=values.get("equal_savings") == "on",
        invest_spare_cash=values.get("invest_spare_cash") == "on",
        use_accounts=values.get("use_saved_accounts") == "on",
        strategy=strategy,
        split=split,
        apr=apr,
        goal=goal,
        starting_savings=starting_savings,
        salary=salary,
        existing=existing if mode == "additional" else Decimal(0),
        salary_start=salary_start,
        salary_end=salary_end,
        missed_salary_dates=skipped,
        comparison_spend=difference,
        one_off_expenses=expenses,
        other=other,
        lump=lump,
        savings=savings,
        save_all=not lump_mode and values.get("save_all") == "on",
        mode=mode,
        start=start,
        months=months,
    )
