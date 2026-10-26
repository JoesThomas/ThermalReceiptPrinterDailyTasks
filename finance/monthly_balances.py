"""Calendar month-end snapshots replay actual forecast allocations, never new ones."""
from copy import deepcopy
from decimal import Decimal
from datetime import timedelta
from finance.money import rounded, format_pounds
from finance.repayment_priority import bank_balances
from finance.savings_interest import Growth, has_recorded_rate

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

    def advance_to(on):
        nonlocal index
        while index < len(movements) and movements[index][0] <= on:
            movement_date, key, amount = movements[index]
            growth.advance(movement_date)
            if by_id[key]['projected'] is not None:
                by_id[key]['projected'] += amount
            index += 1
        growth.advance(on)

    for point in forecast.get('calendar_months', []):
        # Use calendar boundaries even when the first payday is in a later month.
        advance_to(point['date'].replace(day=1) - timedelta(days=1))
        opening_interest = {row['id']: rounded(row['estimated_interest']) for row in rows}
        advance_to(point['date'])
        hsbc, monzo = bank_balances(base, point, inputs.get('monzo_target', ZERO))
        balances = [dict(name=base.get('primary_bank', 'Bank cash'), balance=rounded(hsbc))]
        if inputs.get('monzo_target'):
            balances.append(dict(name='Monzo', balance=rounded(monzo)))
        balances.append(dict(name='Amex - balance owed', balance=point['card_end']))
        for row in rows:
            account = dict(name=row.get('label', row['name']),
                           balance=rounded(row['projected']) if row['projected'] is not None else None)
            if has_recorded_rate(row):
                total = rounded(row['estimated_interest']) if row['balance'] is not None else None
                account['interest_to_date'] = total
                account['interest_month'] = total - opening_interest[row['id']] if total is not None else None
            balances.append(account)
        if not inputs['use_accounts']:
            balances.append(dict(name='Savings (unassigned)', balance=point['savings_end']))
        total_bank = hsbc + monzo
        committed = point.get('committed', ZERO)
        reserve = base.get('reserve_details') or {}
        target = base['buffer'] - reserve.get('gap', ZERO)
        kept = min(max(ZERO, total_bank-committed), target)
        snapshots.append(dict(date=point['date'], funded=point['funded'], accounts=balances,
                              bank_total=rounded(total_bank), committed=rounded(committed),
                              reserves=rounded(kept), unallocated=rounded(max(ZERO,total_bank-committed-kept))))
    return snapshots


def render(page, forecast):
    if forecast.get('print_monthly_balances') is False:
        page.text('Monthly balances and workings are available on the website.')
        return
    interest_note_shown = False
    for month in forecast.get('monthly_balances', []):
        page.section(f"BALANCES AT {month['date']:%B %Y} END".upper())
        page.text(f"On {month['date']:%d %b %Y}")
        if not interest_note_shown and any('interest_month' in row for row in month['accounts']):
            page.text('Interest is estimated before tax, already included in balances; calendar month or part month modelled.')
            interest_note_shown = True
        for row in month['accounts']:
            page.amount(row['name'], row['balance'])
            if 'interest_month' in row:
                page.amount('  Interest this month', row['interest_month'])
        page.amount('Bank money for upcoming costs', month.get('committed', ZERO))
        page.amount('Bank reserves held', month.get('reserves', ZERO))
        page.amount('Unallocated bank surplus', month.get('unallocated', ZERO))
        if not month['funded']:
            page.text('Funding warning: hypothetical balances after a protected balance breach.')


def snapshot(forecast):
    return [dict(date=row['date'].isoformat(), title=f"Balances at {row['date']:%B %Y} end",
                 funded=row['funded'],
                 **{key: format_pounds(row.get(key, ZERO)) for key in ('bank_total','committed','reserves','unallocated')},
                 accounts=[dict(name=a['name'], balance=format_pounds(a['balance']),
                                **({key: format_pounds(a[key]) for key in ('interest_month', 'interest_to_date')}
                                   if 'interest_month' in a else {})) for a in row['accounts']])
            for row in forecast.get('monthly_balances', [])]
