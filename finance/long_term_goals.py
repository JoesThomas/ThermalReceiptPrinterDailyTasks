"""Bounded goal estimates after the funded cash-flow planning horizon."""
from decimal import Decimal
from finance.projection import occurs
from finance.savings_targets import contribution_limit

ZERO = Decimal(0)


def estimate(account, forecast, inputs):
    """Continue the final year's contribution pace; never call this a funded date."""
    if (account['goal_date'] or not account['target'] or account['projected'] is None
            or forecast['run_out'] or inputs.get('salary_end') or inputs['mode'] == 'lump'
            or account.get('cash_reserve_limit')):
        return None
    limit = contribution_limit(account)
    if limit is not None and limit < account['target']:
        return None
    start = occurs(inputs['start'], inputs['months'] - 12)
    contributions = sum((a['total'] for a in account['allocations'] if a['date'] >= start), ZERO)
    contributions += sum((e['amount'] for e in forecast['events']
                          if e.get('savings_account') == account['id'] and start <= e['date'] <= forecast['end']), ZERO)
    monthly = contributions / 12
    rate = account.get('interest_rate') or ZERO
    factor = (1 + rate / 100) ** (Decimal(1) / 12) if account['type'] in {'savings', 'cash_isa'} else Decimal(1)
    if monthly <= ZERO and factor <= 1:
        return None
    balance = account['projected']
    for month in range(1, 1201):
        balance = balance * factor + monthly
        if balance >= account['target']:
            return occurs(inputs['start'], inputs['months'] + month)  # Monthly estimate, not a payment instruction.
    return None
