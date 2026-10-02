"""Private dated savings/investment valuations; no bank transaction history."""
import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock

HISTORY_FILE = Path(__file__).resolve().parents[1] / 'data' / 'wealth_history.json'
_LOCK = RLock()


def amount(value):
    try:
        result = Decimal(str(value)).quantize(Decimal('0.01'))
        if not result.is_finite() or result < 0:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Enter a non-negative amount in pounds.')


def load_history():
    if not HISTORY_FILE.exists():
        return []
    data = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('Balance history is invalid; restore the local file before editing.')
    return data


def _write(rows):
    from storage import write_json
    write_json(HISTORY_FILE, rows)


def record(name, kind, on, balance, deposits=None, withdrawals=None, source='manual', today=None):
    today = today or date.today()
    on = date.fromisoformat(str(on))
    name = name.strip()
    if not name or len(name) > 90 or any(ord(c) < 32 for c in name) or kind not in {'savings', 'investment'} or on > today:
        raise ValueError('Use an account name up to 90 characters, a valid type and a date no later than today.')
    balance = amount(balance)
    known = deposits is not None and withdrawals is not None
    deposits, withdrawals = (amount(deposits), amount(withdrawals)) if known else (None, None)
    with _LOCK:
        rows = load_history()
        matching = [r for r in rows if r['name'].casefold() == name.casefold() and r['kind'] == kind]
        # A website-entered valuation takes precedence over an older local source file.
        if source != 'manual' and any(r['source'] == 'manual' for r in matching):
            return
        existing = next((r for r in matching if r['date'] == on.isoformat()), None)
        row = {'id': existing['id'] if existing else uuid.uuid4().hex, 'name':name, 'kind':kind,
               'date':on.isoformat(), 'balance':str(balance), 'deposits':str(deposits) if known else None,
               'withdrawals':str(withdrawals) if known else None, 'source':source}
        if existing:
            rows[rows.index(existing)] = row
        else:
            if len(rows) >= 20000:
                raise ValueError('Balance history has reached its entry limit.')
            rows.append(row)
            # Inserting a past valuation splits the next interval; flows must be re-entered.
            following = sorted([r for r in matching if r['date'] > row['date']], key=lambda r:r['date'])
            if following:
                following[0]['deposits'] = following[0]['withdrawals'] = None
        _write(rows)


def delete(entry_id):
    with _LOCK:
        rows = load_history()
        removed = next((r for r in rows if r['id'] == entry_id), None)
        if removed:
            following = sorted([r for r in rows if r['name'].casefold() == removed['name'].casefold()
                                and r['kind'] == removed['kind'] and r['date'] > removed['date']], key=lambda r:r['date'])
            if following:
                following[0]['deposits'] = following[0]['withdrawals'] = None
        _write([r for r in rows if r['id'] != entry_id])


def capture_local(savings_data, investments_data, today):
    """Observe existing local values. These are not fresh provider valuations."""
    for row in savings_data.get('accounts', []):
        record(str(row.get('name', 'Savings')), 'savings', today, row.get('balance', 0), source='local observation', today=today)
    updated = investments_data.get('updated')
    try:
        on = date.fromisoformat(str(updated)[:10]) if updated else None
    except ValueError:
        on = None
    if on is None or on > today:
        return
    for row in investments_data.get('accounts', []):
        record(str(row.get('name', 'Investment')), 'investment', on, row.get('value', 0), source='local observation', today=today)


def review(today, month=None):
    month = month or today.strftime('%Y-%m')
    start = date.fromisoformat(month + '-01')
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    rows = [r for r in load_history() if r['date'] <= today.isoformat()]
    accounts = []
    for identity in sorted({(r['kind'], r['name'].casefold()) for r in rows}):
        values = sorted([r for r in rows if (r['kind'], r['name'].casefold()) == identity], key=lambda r:r['date'])
        opening = next((r for r in reversed(values) if r['date'] <= start.isoformat()), None)
        period = [r for r in values if start.isoformat() <= r['date'] < end.isoformat()]
        # If month-start is unavailable, clearly use the first recorded valuation.
        opening = opening or (period[0] if period else None)
        closing = period[-1] if period else opening
        change = amount(closing['balance']) - amount(opening['balance']) if opening and closing and opening['date'] != closing['date'] else None
        between = [r for r in values if opening and closing and opening['date'] < r['date'] <= closing['date']]
        known = bool(between) and all(r['deposits'] is not None and r['withdrawals'] is not None for r in between)
        net = sum((amount(r['deposits']) - amount(r['withdrawals']) for r in between), Decimal(0)) if known else None
        points = values[-24:]
        nums = [float(r['balance']) for r in points]
        lo, hi = min(nums), max(nums)
        first, last = date.fromisoformat(points[0]['date']), date.fromisoformat(points[-1]['date'])
        chart = [{'x': round(30 + 540 * (date.fromisoformat(r['date'])-first).days / max(1,(last-first).days),2), 'y':round(130-100*(float(r['balance'])-lo)/max(1,hi-lo),2), **r} for r in points]
        accounts.append({'name':values[-1]['name'], 'kind':identity[0], 'latest':values[-1], 'balance':amount(values[-1]['balance']),
                         'opening':opening,'closing':closing, 'change':change,
                         'percent':change / amount(opening['balance']) * 100 if change is not None and amount(opening['balance']) else None,
                         'net_contributions':net, 'growth':change-net if change is not None and known else None,
                         'chart':chart, 'points':' '.join(f"{p['x']},{p['y']}" for p in chart), 'low':lo,'high':hi,
                         'entries':list(reversed(values))})
    totals = {kind:sum((a['balance'] for a in accounts if a['kind']==kind),Decimal(0)) for kind in ('savings','investment')}
    return {'accounts':accounts, 'savings':totals['savings'], 'investments':totals['investment'],
            'total':sum(totals.values()), 'month':month}


def receipt_lines(view):
    if not view['accounts']:
        return []
    from textwrap import wrap
    lines = ['SAVINGS / INVESTMENT HISTORY [F]', '-' * 40, 'MONTH: ' + view['month']]
    for account in view['accounts']:
        lines.extend(wrap(account['name'].upper(),40))
        lines.append(('LATEST GBP ' + f"{account['balance']:.2f}" + ' / ' + account['latest']['date']).rjust(40))
        if account['change'] is None:
            lines.append('NEED TWO DATED VALUES TO COMPARE')
        else:
            lines.append(account['opening']['date'] + ' TO ' + account['closing']['date'])
            pct = f" ({account['percent']:+.1f}%)" if account['percent'] is not None else ''
            lines.append(f"BALANCE CHANGE GBP {account['change']:+.2f}" + pct)
            if account['growth'] is not None:
                lines.append(f"NET CONTRIBUTIONS GBP {account['net_contributions']:+.2f}")
                lines.append(f"GROWTH EXCL. FLOWS GBP {account['growth']:+.2f}")
            else:
                lines.append('GROWTH UNKNOWN: RECORD CASH FLOWS')
        lines.append('-' * 40)
    return [part for line in lines for part in wrap(line,40)]


def apply_latest(savings_data, investments_data, view):
    """Use manually maintained valuations in current receipt totals too."""
    savings_data = dict(savings_data, accounts=[dict(r) for r in savings_data.get('accounts', [])])
    investments_data = dict(investments_data, accounts=[dict(r) for r in investments_data.get('accounts', [])])
    for account in view['accounts']:
        target = savings_data if account['kind'] == 'savings' else investments_data
        value_key = 'balance' if account['kind'] == 'savings' else 'value'
        row = next((r for r in target['accounts'] if str(r.get('name','')).casefold() == account['name'].casefold()), None)
        if row is None:
            row = {'name':account['name'], 'include_in_net_cash':False, 'include_in_runway':False}
            target['accounts'].append(row)
        row[value_key] = float(account['balance'])
    dates = [a['latest']['date'] for a in view['accounts'] if a['kind'] == 'investment']
    if dates:
        investments_data['updated'] = min(dates)
    return savings_data, investments_data
