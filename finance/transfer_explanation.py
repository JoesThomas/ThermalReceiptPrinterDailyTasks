"""Explain the existing first-period allocation without recalculating the forecast."""

from decimal import Decimal
from finance.money import format_pounds as pounds

ZERO = Decimal(0)
STRATEGIES = {
    "amex_first": "Bills and food/necessities → Amex → HSBC/Cash/Monzo top-ups → extra savings/investments.",
    "savings_first": "Savings first: the savings allocation takes priority; remaining money can repay Amex.",
    "split": "Split: the selected percentage goes to extra Amex repayment, limited to the debt remaining.",
}


def explain(result):
    first = result["forecast"]["payments"][0]
    data, base = result["inputs"], result["projection"]
    reserve = base.get("reserve_details") or {}
    gap = reserve.get("gap", ZERO)
    tax = reserve.get("tax_reserve", ZERO)
    income = first["salary"] + data["other"]
    lump = data["lump"]
    policy = base.get("repayment_priority")
    available = first["opening"] - (policy["hard"] if policy else base["buffer"]) - first["costs"] - first["variable"]
    rows = [
        ("Bank cash before this period's income", first["opening"] - income - lump),
        ("Salary received this period", first["salary"]),
        ("Other income received this period", data["other"]),
        ("One-off lump sum", lump),
        ("Bank cash after income", first["opening"]),
        ("Protected bank reserve", base["buffer"] - gap - tax),
        ("Protected cash top-up reserve", gap),
        ("Protected tax reserve", tax),
        ("Bills and scheduled payments", first["costs"]),
        ("Everyday spending kept", first["variable"]),
        ("Cash remaining above these commitments", available),
        ("Available allocation from this period's income", first["income_budget"]),
        (
            "Spare bank cash used for extra transfers",
            first["cash_repaid"] + first["cash_invested"] + first.get("instalment_cash", ZERO),
        ),
        ("Extra Amex repayment", first["extra"]),
        ("Extra savings transfers", first["savings"]),
        (
            "Cash left above protected reserves after allocation",
            first.get("essentials_cash_after", first["cash_after_allocation"]) if policy else first["cash_after_allocation"],
        ),
    ]
    if policy:
        rows = [row for row in rows if row[0] not in {'Protected bank reserve', 'Protected cash top-up reserve', 'Protected tax reserve'}]
        rows.insert(5, ('Other protected reserves', policy['hard']))
        rows += [('Reserve targets still to fill', first['reserve_targets']['pending']),
                 ('Cash top-up funded', first['reserve_targets']['cash_transfer'])]
    if first.get('instalment_settled'):
        index = next(i for i, row in enumerate(rows) if row[0] == 'Extra Amex repayment')
        rows.insert(index, ('Instalment balances settled early', first['instalment_settled']))
    moved = ZERO
    destinations = []
    if data["use_accounts"]:
        for account in result["account_plan"]["accounts"]:
            if account["first"]:
                destinations.append(
                    {"name": account.get("label", account["name"]), "amount": pounds(account["first"])}
                )
                moved += account["first"]
    if first["savings"] - moved:
        destinations.append(
            {
                "name": "Savings — choose an account",
                "amount": pounds(first["savings"] - moved),
            }
        )
    investment_destinations = list(destinations)
    if first["extra"]:
        destinations.append(
            {"name": "Amex — extra repayment", "amount": pounds(first["extra"])}
        )
    if policy:
        if first['reserve_targets']['cash_transfer']:
            destinations.append({'name': 'Cash — funded top-up', 'amount': pounds(first['reserve_targets']['cash_transfer'])})
        if first['reserve_targets']['monzo_transfer']:
            destinations.append({'name': 'Monzo — funded top-up', 'amount': pounds(first['reserve_targets']['monzo_transfer'])})
    for item in first.get('instalment_payoffs', []):
        destinations.append({'name': item['name'] + ' — early settlement', 'amount': pounds(item['amount'])})
    if policy:
        ordered = []
        if first['extra']:
            ordered.append({'name': 'Amex — extra repayment', 'amount': pounds(first['extra'])})
        for key, label in [('cash_transfer', 'Cash — funded top-up'), ('monzo_transfer', 'Monzo — funded top-up')]:
            if first['reserve_targets'][key]:
                ordered.append({'name': label, 'amount': pounds(first['reserve_targets'][key])})
        ordered.extend({'name': item['name'] + ' — early settlement', 'amount': pounds(item['amount'])}
                       for item in first.get('instalment_payoffs', []))
        destinations = ordered + investment_destinations
    return {
        "rows": [{"label": label, "amount": pounds(value)} for label, value in rows],
        "destinations": destinations,
        "strategy": STRATEGIES[data["strategy"]],
        "salary_active": first["salary"] > ZERO,
        "reserve_goals_after_amex": bool(policy),
        "spare_cash_enabled": data["invest_spare_cash"],
        "scheduled_savings": pounds(first["automatic_savings"]),
        "funded": first["funded"] and available >= ZERO,
        "date": first["date"].isoformat(),
        "end": first["end"].isoformat(),
    }
