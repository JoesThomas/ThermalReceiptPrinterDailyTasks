"""Optional monthly ceiling while a card is owed or a recorded account is overdrawn."""
from decimal import Decimal
from finance.money import parse

ZERO = Decimal(0)


def recorded_overdraft(base):
    rows = list((base.get('bank_balance_sources') or {}).values())
    rows += [account for row in rows for account in row.get('accounts', [])]
    amounts = [parse(row.get('available', row.get('current'))) for row in rows]
    amounts += [parse(base.get('monzo_balance')), parse((base.get('reserve_details') or {}).get('held'))]
    amounts += [parse(row.get('balance')) for row in base.get('savings_accounts', [])
                if row.get('name', '').casefold().strip() in {'cash', 'physical cash'}]
    return any(amount is not None and amount < ZERO for amount in amounts)


def limited_daily(normal, inputs, days, *, owed=False, overdrawn=False):
    if inputs.get('limit_spending_when_owed') and (owed or overdrawn):
        return min(normal, inputs['debt_spending_cap'] / Decimal(days))
    after = inputs.get('after_debt_spending')
    return after / Decimal(days) if after is not None and not owed and not overdrawn else normal
