"""Calendar month-end snapshots replay actual forecast allocations, never new ones."""
from copy import deepcopy
from decimal import Decimal
from finance.money import rounded, format_pounds
from finance.repayment_priority import bank_balances
from finance.savings_interest import Growth

ZERO = Decimal(0)


def build(base, inputs, forecast, plan, today):
    rows = deepcopy(plan['accounts']) if inputs['use_accounts'] else []
    for row in rows:
        row['projected'] = row['balance']
        row['goal_date'] = None
    growth = Growth(rows, today)
    by_id = {row['id']: row for row in rows}
    movements = [(a['date'], row['id'], a['total']) for row in rows for a in row['allocations']]
    movements.extend((e['date'], e.get('savings_account'), e['amount'])
                     for e in forecast['events'] + forecast['reserve_transfers']
                     if e.get('savings_account') in by_id)
    movements.sort(key=lambda item: item[0])
    index = 0
    snapshots = []
    for point in forecast.get('calendar_months', []):
        while index < len(movements) and movements[index][0] <= point['date']:
            on, key, amount = movements[index]
            growth.advance(on)
            if by_id[key]['projected'] is not None:
                by_id[key]['projected'] += amount
            index += 1
        growth.advance(point['date'])
        hsbc, monzo = bank_balances(base, point, inputs.get('monzo_target', ZERO))
        balances = [dict(name=base.get('primary_bank', 'Bank cash'), balance=rounded(hsbc))]
        if inputs.get('monzo_target'):
            balances.append(dict(name='Monzo', balance=rounded(monzo)))
        balances.append(dict(name='Amex - balance owed', balance=point['card_end']))
        balances.extend(dict(name=row.get('label', row['name']),
                             balance=rounded(row['projected']) if row['projected'] is not None else None)
                        for row in rows)
        if not inputs['use_accounts']:
            balances.append(dict(name='Savings (unassigned)', balance=point['savings_end']))
        snapshots.append(dict(date=point['date'], funded=point['funded'], accounts=balances))
    return snapshots


def render(page, forecast):
    for month in forecast.get('monthly_balances', []):
        page.section(f"BALANCES AT {month['date']:%B %Y} END".upper())
        page.text(f"On {month['date']:%d %b %Y}")
        for row in month['accounts']:
            page.amount(row['name'], row['balance'])
        if not month['funded']:
            page.text('Funding warning: hypothetical balances after a protected balance breach.')


def snapshot(forecast):
    return [dict(date=row['date'].isoformat(), title=f"Balances at {row['date']:%B %Y} end",
                 funded=row['funded'],
                 accounts=[dict(name=a['name'], balance=format_pounds(a['balance'])) for a in row['accounts']])
            for row in forecast.get('monthly_balances', [])]
