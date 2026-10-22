"""Priority funding of dated cash pots, independent of salary or employment."""
from datetime import date
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import hashlib
import secrets
from finance.money import parse, ZERO
from receipt.local_time import uk_today
from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / 'data' / 'annual_funds.json'


def defaults():
    return {'version': 1, 'enabled': False, 'tax_enabled': True, 'tax_source': 'rental', 'tax_target': '0.00',
            'tax_paid': '0.00', 'tax_due': '', 'tax_checked': '', 'tax_balance': '0.00', 'tax_inside': True,
            'tax_destination': 'Tax reserve', 'tax_bill_name': '', 'pots': [], 'transfers': []}


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1 or any(type(value.get(k)) is not bool for k in ('enabled', 'tax_enabled', 'tax_inside')):
        raise ValueError('Invalid annual fund settings.')
    if value.get('tax_source') not in ('rental', 'manual') or not isinstance(value.get('pots'), list) or not isinstance(value.get('transfers'), list) or len(value['pots']) > 50 or len(value['transfers']) > 2000:
        raise ValueError('Invalid fund records.')
    for field in ('tax_target', 'tax_paid', 'tax_balance'):
        if parse(value.get(field)) is None or not 0 <= parse(value[field]) <= 10000000:
            raise ValueError('Enter valid tax amounts.')
    for field in ('tax_due', 'tax_checked'):
        if value.get(field):
            date.fromisoformat(value[field])
    if value['enabled'] and value['tax_enabled'] and value['tax_source'] == 'manual' and (not value['tax_due'] or not value['tax_checked']):
        raise ValueError('Enter the tax deadline and estimate check date.')
    ids = set()
    names = {'tax reserve'} if value['tax_enabled'] else set()
    from actions.day_assistant import text
    text(value.get('tax_destination'), 100)
    if value.get('tax_bill_name'):
        text(value['tax_bill_name'], 100)
    for row in value['pots']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or len(row['id']) != 24 or row['id'] in ids:
            raise ValueError('Invalid savings pot.')
        ids.add(row['id'])
        name = text(row.get('name'), 100)
        if name.casefold() in names:
            raise ValueError('Use a distinct name for each cash pot.')
        names.add(name.casefold())
        text(row.get('destination'), 100)
        if row.get('bill_name'):
            text(row['bill_name'], 100)
        date.fromisoformat(row['due'])
        if type(row.get('inside')) is not bool or type(row.get('priority')) is not int or not 1 <= row['priority'] <= 100:
            raise ValueError('Invalid pot priority or location.')
        for field in ('target', 'balance'):
            if parse(row.get(field)) is None or not 0 <= parse(row[field]) <= 10000000:
                raise ValueError('Invalid pot amount.')
    for row in value['transfers']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not isinstance(row.get('pot'), str) or row.get('status') not in ('completed', 'matched') or type(row.get('inside')) is not bool:
            raise ValueError('Invalid transfer record.')
        date.fromisoformat(row['date'])
        if parse(row.get('amount')) is None or parse(row['amount']) <= 0:
            raise ValueError('Invalid transfer amount.')


def store():
    return PrivateStore(FILE, default=defaults, validate=validate)


def pots(value=None, today=None):
    today = today or uk_today()
    value = value if value is not None else store().read()
    rows = []
    if value['tax_enabled']:
        from finance.rental_tax import load, estimate
        previous = load()
        rental = estimate(previous, today)
        if value['tax_source'] == 'rental':
            if rental is None:
                raise ValueError('Update the rental-tax estimate or choose a manual net tax estimate.')
            target = rental['tax']
            # This is a savings deadline, not a claim about an HMRC payment deadline.
            due = value['tax_due'] or rental['rules']['end']
        else:
            target = parse(value['tax_target'])
            due = value['tax_due']
        held = max(parse(value['tax_balance']), parse(previous.get('reserved'), ZERO))
        rows.append({'id': 'tax', 'name': 'Tax reserve', 'target': max(ZERO, target - parse(value['tax_paid'])),
                     'balance': held, 'due': due, 'inside': value['tax_inside'], 'priority': 0,
                     'destination': value['tax_destination'], 'bill_name': value.get('tax_bill_name', ''), 'checked': value['tax_checked'] or None})
    rows += [{**r, 'target': parse(r['target']), 'balance': parse(r['balance'])} for r in value['pots']]
    return sorted(rows, key=lambda r: (r['priority'], r['due'], r['name'].casefold()))


def protected_reserve():
    value = store().read()
    pending = sum((parse(t['amount']) for t in value['transfers'] if not t['inside'] and t['status'] == 'completed'), ZERO)
    if not value['enabled']:
        from finance.rental_tax import protected_reserve as legacy
        return legacy() + pending
    legacy_reserve = ZERO
    if not value['tax_enabled']:
        from finance.rental_tax import protected_reserve as legacy
        legacy_reserve = legacy()
    return sum((r['balance'] for r in pots(value) if r['inside']), ZERO) + pending + legacy_reserve


def plan(budget, today=None, value=None, *, valid=True, covered=()):
    today = today or uk_today()
    value = value if value is not None else store().read()
    result = {'enabled': value['enabled'], 'rows': [], 'total': ZERO, 'remaining': budget, 'valid': valid, 'error': None}
    if not value['enabled']:
        return result
    try:
        records = pots(value, today)
    except (ValueError, OSError) as error:
        result.update(valid=False, error=str(error))
        return result
    left = max(ZERO, budget or ZERO) if valid else ZERO
    for row in records:
        due = date.fromisoformat(row['due'])
        gap = max(ZERO, row['target'] - row['balance'])
        months = max(1, (due.year - today.year) * 12 + due.month - today.month + (due.day >= today.day))
        completed = sum((parse(t['amount']) for t in value['transfers'] if t['pot'] == row['id'] and t['date'][:7] == today.isoformat()[:7]), ZERO)
        wanted = max(ZERO, ((gap + completed) / months).quantize(Decimal('.01'), rounding=ROUND_CEILING) - completed)
        already_reserved = row['id'] in covered
        amount = ZERO if already_reserved else min(left, wanted, gap)
        left -= amount
        identity = hashlib.sha256(f"{today:%Y-%m}:{row['id']}:{completed}:{amount}".encode()).hexdigest()
        result['rows'].append({**row, 'gap': gap, 'monthly': wanted, 'suggested': amount, 'covered_by_bill': already_reserved, 'shortfall': ZERO if already_reserved else wanted - amount, 'transfer_id': identity})
    result.update(total=sum((r['suggested'] for r in result['rows']), ZERO), remaining=left)
    return result


def complete(identifier, pot_id, amount, *, today=None):
    today = today or uk_today()
    amount = parse(amount)
    def change(value):
        if any(t['id'] == identifier for t in value['transfers']):
            return
        row = next((p for p in pots(value, today) if p['id'] == pot_id), None)
        if not row or amount is None or not ZERO < amount <= max(ZERO, row['target'] - row['balance']):
            raise ValueError('Refresh the fund plan before recording this transfer.')
        if pot_id == 'tax':
            value['tax_balance'] = str(row['balance'] + amount)
        else:
            next(p for p in value['pots'] if p['id'] == pot_id)['balance'] = str(row['balance'] + amount)
        value['transfers'].append({'id': identifier, 'pot': pot_id, 'amount': str(amount), 'date': today.isoformat(),
                                   'inside': row['inside'], 'status': 'matched' if row['inside'] else 'completed', 'bank_key': None})
    store().update(change)


def bank_candidates(transactions):
    rows = []
    seen = set()
    for tx in transactions:
        amount = parse(tx.get('amount'))
        if tx.get('_source_provider') == 'AMEX' or amount is None or str(tx.get('transaction_type', '')).upper() == 'CREDIT' or not (amount < 0 or str(tx.get('transaction_type', '')).upper() == 'DEBIT'):
            continue
        try:
            on = date.fromisoformat(str(tx.get('timestamp') or tx.get('date'))[:10])
        except ValueError:
            continue
        identity = str(tx.get('normalised_provider_transaction_id') or tx.get('provider_transaction_id') or tx.get('transaction_id') or [str(on), str(amount), tx.get('description')])
        key = hashlib.sha256((str(tx.get('_source_provider')) + identity).encode()).hexdigest()
        if key not in seen:
            rows.append({'key': key, 'date': on.isoformat(), 'amount': abs(amount)})
            seen.add(key)
    return rows


def match(transfer_id, bank_key, transactions):
    candidate = next((r for r in bank_candidates(transactions) if r['key'] == bank_key), None)
    def change(value):
        row = next((r for r in value['transfers'] if r['id'] == transfer_id), None)
        if not candidate or not row or row['status'] != 'completed' or any(t.get('bank_key') == bank_key for t in value['transfers']) or candidate['amount'] != parse(row['amount']) or abs((date.fromisoformat(candidate['date']) - date.fromisoformat(row['date'])).days) > 3:
            raise ValueError('Choose a matching posted bank debit for this transfer.')
        row.update(status='matched', bank_key=bank_key)
    store().update(change)


def link_earmarks(events):
    """A linked scheduled bill protects the same money; remove that part of the buffer.

    Cash costs stay unchanged. Allocation paths hold linked earmarks until the
    period containing the actual bill, rather than reserving both amounts.
    """
    value = store().read()
    if not value['enabled']:
        return ZERO
    released = ZERO
    def name_key(text):
        return ' '.join(str(text).casefold().split())
    for row in pots(value):
        if not row['inside']:
            continue
        name = row.get('bill_name') or row['name']
        remaining = row['balance']
        for event in sorted(events, key=lambda e: e['date']):
            if name_key(event['name']) != name_key(name):
                continue
            event.setdefault('cash_fund_ids', []).append(row['id'])
            room = max(ZERO, event['amount'] - event.get('cash_fund_reserved', ZERO))
            credit = min(remaining, room)
            remaining -= credit
            released += credit
            event['cash_fund_reserved'] = event.get('cash_fund_reserved', ZERO) + credit
            if remaining == 0:
                break
    return released
