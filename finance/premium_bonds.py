"""Private prize ledger and day-weighted balances; never annualises partial returns."""
import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import fcntl
FILE = Path(__file__).resolve().parents[1] / 'data' / 'premium_bonds.json'

def money(value, positive=False):
    try:
        result = Decimal(str(value)).quantize(Decimal('.01'))
        if not result.is_finite() or result < 0 or (positive and result <= 0):
            raise ValueError()
        return result
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError('Enter a valid non-negative amount.') from None

def load():
    if not FILE.exists():
        return {'prizes': [], 'balances': [], 'complete_through': {}}
    value = json.loads(FILE.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not all(isinstance(value.get(k), list) for k in ('prizes', 'balances')):
        raise ValueError('Premium Bonds history is invalid. Restore the private file.')
    value.setdefault('complete_through', {})
    validate_data(value)
    return value

def validate_data(value):
    if not isinstance(value, dict) or not all(isinstance(value.get(key), list) for key in ('prizes', 'balances')) or not isinstance(value.get('complete_through', {}), dict):
        raise ValueError('Invalid Premium Bonds ledger.')
    try:
        for kind in ('prizes', 'balances'):
            identifiers = set()
            for row in value[kind]:
                if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in identifiers:
                    raise ValueError()
                identifiers.add(row['id'])
                date.fromisoformat(row['date'])
                money(row['amount'], positive=kind == 'prizes')
        for year, through in value.get('complete_through', {}).items():
            if not 1900 <= int(year) <= 9999 or date.fromisoformat(through).year != int(year):
                raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('Invalid Premium Bonds ledger.') from None

@contextmanager
def edit():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(FILE.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = load()
        yield value
        temporary = FILE.with_name(FILE.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False)
            temporary.replace(FILE)
        finally:
            temporary.unlink(missing_ok=True)

def valid_date(value, today):
    try:
        on = date.fromisoformat(str(value))
        if on > today:
            raise ValueError()
        return on
    except (TypeError, ValueError):
        raise ValueError('Use a valid date no later than today.') from None

def record(kind, on, amount, today=None):
    today = today or date.today()
    on = valid_date(on, today).isoformat()
    amount = str(money(amount, positive=kind == 'prize'))
    if kind not in {'prize', 'balance'}:
        raise ValueError('Unknown record type.')
    with edit() as value:
        if kind == 'balance':
            rows = value['balances']
            existing = next((r for r in rows if r['date'] == on), None)
            if existing:
                existing['amount'] = amount
            else:
                rows.append({'id': secrets.token_hex(12), 'date': on, 'amount': amount})
        else:
            # Avoid entering an already imported payment a second time.
            if any(r['date'] == on and money(r['amount']) == money(amount) and r.get('bank_key') for r in value['prizes']):
                raise ValueError('A bank prize of this date and amount is already recorded.')
            value['prizes'].append({'id': secrets.token_hex(12), 'date': on, 'amount': amount, 'source': 'manual'})
        value['complete_through'].pop(str(date.fromisoformat(on).year), None)

def remove(kind, identifier):
    if kind not in {'prize', 'balance'}:
        raise ValueError('Unknown record type.')
    with edit() as value:
        rows = value['prizes' if kind == 'prize' else 'balances']
        row = next((r for r in rows if r['id'] == identifier), None)
        if row is None:
            raise ValueError('Record not found.')
        if kind == 'prize' and row.get('bank_key'):
            # Keep a tombstone so the next bank refresh cannot resurrect a rejected import.
            row['excluded'] = True
        else:
            rows.remove(row)
        value['complete_through'].pop(str(date.fromisoformat(row['date']).year), None)

def confirm(year, today):
    year = int(year)
    if year < 1900 or year > today.year:
        raise ValueError('Use a past or current year.')
    with edit() as value:
        value['complete_through'][str(year)] = min(today, date(year, 12, 31)).isoformat()

def capture(transactions, classify, incoming, internal, dated):
    """Keep only prize dates/amounts and hashed identities, never raw bank records."""
    rows = []
    occurrences = {}
    for tx in transactions:
        if not incoming(tx) or internal(tx) or classify(tx) != 'PREMIUM BONDS':
            continue
        on = dated(tx)
        if on is None:
            continue
        try:
            amount = money(abs(Decimal(str(tx.get('amount') or 0))))
        except (ValueError, TypeError, InvalidOperation):
            continue
        if amount <= 0:
            continue
        identifier = tx.get('transaction_id') or tx.get('id')
        fingerprint = json.dumps([on.isoformat(), str(amount), str(tx.get('description') or '').casefold(),
                                  str(tx.get('merchant_name') or '').casefold(), str(tx.get('reference') or '').casefold()])
        if identifier:
            identity = json.dumps([str(tx.get('_source_provider') or ''), str(identifier)])
        else:
            ordinal = occurrences.get(fingerprint, 0)
            occurrences[fingerprint] = ordinal + 1
            identity = fingerprint + ':' + str(ordinal)
        rows.append((on.isoformat(), str(amount), hashlib.sha256(identity.encode()).hexdigest()))
    if not rows:
        return
    with edit() as value:
        keys = {row.get('bank_key') for row in value['prizes']}
        for on, amount, key in rows:
            if key in keys:
                continue
            manual = next((row for row in value['prizes'] if row['date'] == on and money(row['amount']) == money(amount)
                           and row.get('source') == 'manual' and not row.get('bank_key')), None)
            if manual:
                manual['bank_key'] = key
                manual['source'] = 'manual / bank matched'
            else:
                value['prizes'].append({'id': secrets.token_hex(12), 'date': on, 'amount': amount,
                                        'bank_key': key, 'source': 'bank'})
                value['complete_through'].pop(str(date.fromisoformat(on).year), None)
            keys.add(key)

def review(today, year=None):
    year = int(year or today.year)
    if not 1900 <= year <= today.year:
        raise ValueError('Use a past or current year.')
    value = load()
    start, end = date(year, 1, 1), min(today, date(year, 12, 31))
    prizes = sorted([row for row in value['prizes'] if not row.get('excluded') and start.isoformat() <= row['date'] <= end.isoformat()], key=lambda r:r['date'], reverse=True)
    balances = sorted([row for row in value['balances'] if row['date'] <= end.isoformat()], key=lambda r:r['date'])
    first = max(start, date.fromisoformat(balances[0]['date'])) if balances else None
    average = percent = None
    period_total = Decimal(0)
    if first:
        total = Decimal(0)
        on = first
        index, balance = 0, Decimal(0)
        while on <= end:
            while index < len(balances) and balances[index]['date'] <= on.isoformat():
                balance = money(balances[index]['amount'])
                index += 1
            total += balance
            on += timedelta(days=1)
        average = total / ((end - first).days + 1)
        period_total = sum((money(r['amount']) for r in prizes if r['date'] >= first.isoformat()), Decimal(0))
        percent = period_total / average * 100 if average > 0 else None
    months = []
    for month in range(1, end.month + 1):
        total = sum((money(r['amount']) for r in prizes if int(r['date'][5:7]) == month), Decimal(0))
        months.append({'label': date(year, month, 1).strftime('%b'), 'total': total})
    maximum = max((m['total'] for m in months), default=Decimal(0))
    cumulative = Decimal(0)
    for month in months:
        cumulative += month['total']
        month['cumulative'] = cumulative
        month['width'] = float(month['total'] / maximum * 100) if maximum else 0
    complete = value['complete_through'].get(str(year), '') >= end.isoformat()
    return dict(year=year, start=first, end=end, prizes=prizes, balances=list(reversed(balances)),
                total=sum((money(r['amount']) for r in prizes), Decimal(0)), average=average,
                percent=percent, period_total=period_total, months=months, complete=complete,
                full_year=complete and year < today.year and first == start)

def receipt_lines(today):
    result = review(today)
    if not result['prizes'] and not result['balances']:
        return []
    lines = ['PREMIUM BONDS / RECORDED YTD', f"WINNINGS {result['year']} GBP {result['total']:.2f}"]
    if result['percent'] is not None:
        if result['period_total'] != result['total']:
            lines.append(f"PERIOD PRIZES GBP {result['period_total']:.2f}")
        lines += [f"RECORDED RETURN {result['percent']:.2f}%", f"AVG HELD GBP {result['average']:.2f}",
                  f"{result['start']:%d %b} TO {result['end']:%d %b}"]
    else:
        lines.append('ADD DATED BALANCE FOR RETURN')
    if not result['complete']:
        lines.append('PRIZE HISTORY MAY BE INCOMPLETE')
    return lines
