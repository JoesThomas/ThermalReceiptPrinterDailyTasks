"""Explicit, fee-free instalment settlements inside a hypothetical forecast only."""
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
from finance.money import parse, rounded
from finance.repayment_identity import names

ZERO = Decimal(0)
PREFIX = 'payoff_plan_'


def options(records):
    """A confirmation belongs to the recorded balance, not just a merchant name."""
    from finance.test_forecast import is_amex
    result = []
    for row in records:
        balance = parse(row.get('remaining_balance', row.get('balance')))
        payment = parse(row.get('monthly_payment', row.get('amount')))
        if (row.get('type', 'payment_plan') != 'payment_plan' or is_amex(row.get('name', ''))
                or balance is None or balance <= 0 or payment is None or payment <= 0):
            continue
        identity = json.dumps({key: row.get(key) for key in (
            'name', 'monthly_commitment_name', 'remaining_balance', 'balance',
            'monthly_payment', 'amount', 'next_payment', 'due_date', 'schedule',
            'payments_remaining', 'end_date')}, sort_keys=True, default=str)
        identifier = hashlib.sha256(identity.encode()).hexdigest()[:32]
        result.append(dict(id=identifier, name=str(row.get('name') or 'Instalment plan'),
                           balance=balance, aliases=names(row), record=row))
    return result


def prepare(base, inputs, today):
    if not inputs.get('early_payoff'):
        return []
    candidates = options(base.get('repayment_options', []))
    wanted = set(inputs.get('payoff_plans', []))
    if wanted - {row['id'] for row in candidates}:
        raise ValueError('An early-payoff plan has changed or is unavailable. Review its balance and select it again.')
    states = []
    for row in candidates:
        if row['id'] not in wanted:
            continue
        linked = []
        for event in base['events']:
            if event['date'] < today or event.get('scenario_expense'):
                continue
            aliases = names(event)
            matching = [other for other in candidates if aliases & other['aliases']]
            if not aliases & row['aliases']:
                continue
            if (len(matching) != 1 or event.get('undated') or event.get('savings_account')
                    or event.get('cash_fund_reserved') or event.get('amex_statement_protection')):
                raise ValueError('Early payoff needs a unique, dated instalment schedule: ' + row['name'])
            linked.append(event)
        if not linked:
            raise ValueError('No future payment schedule found for early payoff: ' + row['name'])
        remaining = row['balance']
        for event in sorted(linked, key=lambda e: e['date']):
            event['instalment_plan'] = row['id']
            event['amount'] = min(event['amount'], remaining)
            remaining -= event['amount']
        states.append(dict(id=row['id'], name=row['name'], opening=row['balance'],
                           remaining=row['balance'], settlement=None, events=linked))
    return states


def settle(states, on, current_events, budget, funded):
    """Smallest affordable whole balance first; release replaced bills exactly once."""
    settlements = []
    released = total = ZERO
    if not funded:
        return settlements, released, total
    for row in sorted(states, key=lambda r: (r['remaining'], r['name'], r['id'])):
        remaining = row['remaining']
        if remaining <= 0 or row['settlement']:
            continue
        future = [e for e in row['events'] if e['date'] >= on and e['amount'] > 0]
        if not future or not any(e['date'] > on for e in future):
            continue
        reserved = sum((e['amount'] for e in current_events if e.get('instalment_plan') == row['id']), ZERO)
        extra = max(ZERO, remaining - reserved)
        if rounded(extra, rounding=ROUND_DOWN) != extra or extra > budget:
            continue
        entry = dict(id=row['id'], name=row['name'], date=on, amount=remaining,
                     scheduled_replaced=reserved, extra=extra,
                     payments_removed=len(future), final_scheduled=max(e['date'] for e in future))
        row['settlement'] = entry
        row['remaining'] = ZERO
        for event in future:
            event['amount'] = ZERO
        settlements.append(entry)
        budget -= extra
        released += reserved
        total += remaining
    return settlements, released, total


def summary(states):
    return [dict(id=r['id'], name=r['name'], opening=r['opening'], remaining=r['remaining'],
                 settlement=r['settlement']) for r in states]
