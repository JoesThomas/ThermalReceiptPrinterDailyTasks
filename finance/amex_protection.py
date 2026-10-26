"""Statement-based Amex payment protection; plans never count as settled payments."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path

from finance.projection import day, money
from receipt.local_time import uk_today
from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / 'data' / 'amex_payment_protection.json'
ZERO = Decimal('0.00')
MODES = ('unknown', 'none', 'minimum', 'fixed', 'full')


def defaults():
    return {'version': 1, 'enabled': False, 'balance_alert_enabled': True, 'balance_alert_threshold': '1000.00', 'source': 'auto', 'manual_statement': {},
            'dd_mode': 'unknown', 'dd_amount': None, 'dd_date': None,
            'paying_account': 'HSBC', 'carried_balance': 'unknown',
            'confirmed_statement': None, 'confirmed_total': '0.00',
            'confirmed_through': None, 'evidence': {}}


def statement(row):
    if not isinstance(row, dict):
        return None
    balance = money(row.get('balance'))
    on, due = day(row.get('date')), day(row.get('due'))
    if balance is None or balance < 0 or not on or not due or due < on or (due - on).days > 62:
        return None
    return {'balance': balance, 'date': on, 'due': due}


def validate(value):
    if not isinstance(value, dict) or (type(value.get('version')) is not int or value.get('version') != 1) or type(value.get('enabled')) is not bool:
        raise ValueError('Invalid Amex payment protection settings.')
    if value.get('source') not in ('auto', 'manual') or value.get('dd_mode') not in MODES or value.get('paying_account') not in ('HSBC', 'MONZO') or value.get('carried_balance') not in ('unknown', 'yes', 'no'):
        raise ValueError('Invalid Amex payment protection option.')
    threshold=money(value.get('balance_alert_threshold','1000'))
    if type(value.get('balance_alert_enabled',True)) is not bool or threshold is None or not 0<threshold<=10000000:
        raise ValueError('Choose an Amex balance warning threshold above £0 and up to £10,000,000.')
    for name in ('dd_amount', 'confirmed_total'):
        number = money(value.get(name))
        if (name == 'confirmed_total' or value.get(name) is not None) and (number is None or not 0 <= number <= 10000000):
            raise ValueError('Use a valid non-negative payment amount.')
    for name in ('dd_date', 'confirmed_statement', 'confirmed_through'):
        if value.get(name) is not None and not day(value[name]):
            raise ValueError('Use valid payment dates.')
    manual = value.get('manual_statement')
    if not isinstance(manual, dict) or (manual and statement(manual) is None):
        raise ValueError('Enter the statement date, full statement balance and payment due date.')
    if value['enabled'] and value['source'] == 'manual' and not manual:
        raise ValueError('Enter a complete manual statement.')
    evidence = value.get('evidence')
    if not isinstance(evidence, dict) or not isinstance(evidence.get('payments', []), list):
        raise ValueError('Invalid Amex payment evidence.')
    if evidence:
        if evidence.get('last_known_current') is not None and money(evidence['last_known_current']) is None:
            raise ValueError('Invalid retained Amex balance.')
        if evidence.get('last_known_checked_at') is not None and not day(evidence['last_known_checked_at']):
            raise ValueError('Invalid retained Amex check date.')
        if not isinstance(evidence.get('balances'), dict) or not day(evidence.get('checked_at')):
            raise ValueError('Invalid Amex balance evidence.')
        if evidence.get('statement') and statement(evidence['statement']) is None:
            raise ValueError('Invalid bank statement evidence.')
        if type(evidence.get('amex_ok')) is not bool or type(evidence.get('funding_complete', False)) is not bool:
            raise ValueError('Invalid Amex source coverage.')
        for key in ('daily', 'buffer'):
            if key in evidence and (money(evidence[key]) is None or money(evidence[key]) < 0):
                raise ValueError('Invalid Amex funding evidence.')
        if not isinstance(evidence.get('costs', []), list):
            raise ValueError('Invalid Amex bill coverage.')
        for cost in evidence.get('costs', []):
            if not isinstance(cost, dict) or not day(cost.get('date')) or money(cost.get('amount'), ZERO) <= 0:
                raise ValueError('Invalid Amex bill coverage.')
        for payment in evidence.get('payments', []):
            if not isinstance(payment, dict) or not day(payment.get('date')) or money(payment.get('amount'), ZERO) <= 0 or not isinstance(payment.get('card_key'), str):
                raise ValueError('Invalid Amex payment evidence.')


def store(path=None):
    return PrivateStore(path or FILE, default=defaults, validate=validate, max_bytes=1_000_000)


def card_key(identifier):
    return hashlib.sha256(str(identifier).encode()).hexdigest() if identifier else ''


def payment_rows(transactions):
    """Only Amex-side payment credits qualify; merchant refunds and bank debits do not."""
    result, seen = [], set()
    for tx in transactions:
        if tx.get('_source_provider') != 'AMEX' or str(tx.get('transaction_type', '')).upper() != 'CREDIT' or tx.get('currency', 'GBP') != 'GBP':
            continue
        text = ' '.join(str(tx.get('description') or '').upper().split())
        if not (text.startswith('PAYMENT RECEIVED') or text.startswith('PAYMENT THANK YOU') or text.startswith('PAYMENT - THANK YOU') or text.startswith('DIRECT DEBIT PAYMENT')):
            continue
        if any(term in text for term in ('REFUND', 'REVERSE', 'REVERSAL', 'CANCEL')):
            continue
        on, amount = day(tx.get('timestamp') or tx.get('date')), money(tx.get('amount'))
        if not on or amount is None or amount == 0:
            continue
        identity = (str(tx.get('_source_account') or ''), str(tx.get('normalised_provider_transaction_id') or tx.get('provider_transaction_id') or tx.get('transaction_id') or (str(on), str(amount), text)))
        if identity in seen:
            continue
        seen.add(identity)
        result.append({'date': on.isoformat(), 'amount': str(abs(amount)), 'card_key': card_key(tx.get('_source_account'))})
    return result


def evidence(balances, transactions, summary, checked_at=None):
    from finance.amex_interest import detect as detect_interest
    card = balances.get('AMEX', {})
    source = statement({'date': card.get('last_statement_date'), 'balance': card.get('last_statement_balance'), 'due': card.get('payment_due_date')})
    if card.get('currency', 'GBP') != 'GBP':
        source = None
    coverage = summary.get('source_coverage', [])
    amex_ok = any(r.get('provider') == 'AMEX' and r.get('status') == 'Loaded' for r in coverage)
    if not coverage:
        amex_ok = summary.get('bank_data_status') == 'complete' and bool(card)
    return {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
            'balances': {p: str(money(balances.get(p, {}).get('available'))) if money(balances.get(p, {}).get('available')) is not None else None for p in ('HSBC', 'MONZO')},
            'statement': {'date': source['date'].isoformat(), 'due': source['due'].isoformat(), 'balance': str(source['balance'])} if source else {},
            'currency': card.get('currency', 'GBP'), 'card_key': card.get('statement_card_key', ''), 'current': str(money(card.get('current'))) if money(card.get('current')) is not None else None,
            'minimum': str(money(card.get('payment_due'))) if money(card.get('payment_due')) is not None else None,
            'interest_seen': bool(detect_interest(transactions)),
            'amex_ok': amex_ok, 'from': summary.get('requested_from'), 'payments': payment_rows(transactions)}


def capture(balances, transactions, summary, *, path=None, checked_at=None):
    observed = evidence(balances, transactions, summary, checked_at)
    # An unsuccessful refresh cannot erase the previous bank evidence.
    if not balances.get('AMEX'):
        return
    # Reuse the normal forecast's bill matching and spending estimate. Disable
    # protection only for this baseline calculation to avoid counting it twice.
    try:
        from services.live_pipeline import build_subscription_status
        from finance.receipt import load_finance_settings
        from finance.projection import build_projection
        status = build_subscription_status(transactions)
        on = day(observed['checked_at'])
        baseline = build_projection(balances, transactions, status['monthly'], status['yearly'],
                                    load_finance_settings(), on, bank_status=summary.get('bank_data_status', 'unavailable'),
                                    horizon=62, protection_override=assess(defaults(), today=on))
        from finance.test_forecast import is_amex
        observed['costs'] = [{'date': e['date'].isoformat(), 'amount': str(e['amount'])} for e in baseline['events'] if not is_amex(e['name'])]
        observed['daily'] = str(baseline['daily_cost'])
        observed['buffer'] = str(baseline['buffer'])
        observed['funding_complete'] = baseline['valid']
    except (ValueError, OSError, KeyError, TypeError, RuntimeError):
        observed['funding_complete'] = False
    def update(value):
        previous=value.get('evidence',{})
        current=money(observed.get('current'))
        if observed.get('amex_ok') and observed.get('currency','GBP')=='GBP' and current is not None:
            observed['last_known_current']=str(current)
            observed['last_known_checked_at']=observed['checked_at']
        else:
            last=money(previous.get('last_known_current',previous.get('current')))
            if last is not None and previous.get('currency','GBP')=='GBP':
                observed['last_known_current']=str(last)
                observed['last_known_checked_at']=previous.get('last_known_checked_at',previous.get('checked_at'))
        value.update(evidence=observed)
    store(path).update(update)


def mark_failed(*, path=None):
    """Retain previous balances/payments, but do not present them as a successful check."""
    target = store(path)
    if not target.path.exists():
        return
    def change(value):
        if value.get('evidence'):
            value['evidence']['refresh_failed'] = True
    target.update(change)


def assess(value=None, *, today=None, observed=None):
    value = value if value is not None else store().read()
    today = today or uk_today()
    observed = observed if observed is not None else value.get('evidence', {})
    result = {'enabled': value['enabled'], 'config': value, 'warnings': [], 'statement': None,
              'valid': True, 'remaining': ZERO, 'confirmed': ZERO, 'scheduled': None,
              'reserve': ZERO, 'cash_gap': None, 'coverage': None, 'current': money(observed.get('current'))}
    if not value['enabled']:
        return result
    if observed.get('currency', 'GBP') != 'GBP':
        result['valid'] = False
        result['warnings'].append('Amex: payment protection currently requires a GBP card.')
        return result
    source = value['manual_statement'] if value['source'] == 'manual' else observed.get('statement', {})
    bill = statement(source)
    result['statement'] = bill
    if not bill or bill['date'] > today:
        result['valid'] = False
        result['warnings'].append('Amex: enter or refresh the statement balance and due date.')
        return result
    fresh = bool(not observed.get('refresh_failed') and day(observed.get('checked_at')) and 0 <= (today - day(observed['checked_at'])).days <= 1)
    through = day(value.get('confirmed_through'))
    manual = money(value['confirmed_total'], ZERO) if day(value.get('confirmed_statement')) == bill['date'] and through and bill['date'] < through <= today else ZERO
    key = observed.get('card_key')
    paid = sum((money(row['amount'], ZERO) for row in observed.get('payments', [])
                if key and row['card_key'] == key and bill['date'] < day(row['date']) <= today), ZERO)
    confirmed = min(bill['balance'], max(manual, paid))
    remaining = max(ZERO, bill['balance'] - confirmed)
    mode = value['dd_mode']
    due = bill['due']
    collection = day(value.get('dd_date')) or due
    if value.get('dd_date') and not bill['date'] <= collection <= due:
        result['warnings'].append('Amex: confirm the Direct Debit date for this statement.')
        collection = due
    expected = money(value.get('dd_amount'))
    if mode == 'none':
        scheduled = ZERO
    elif mode == 'fixed':
        scheduled = expected
    elif mode == 'minimum':
        scheduled = expected if expected is not None else money(observed.get('minimum'))
    elif mode == 'full':
        scheduled = expected if expected is not None else remaining
    else:
        scheduled = None
    reserve = max(remaining, scheduled or ZERO)
    # A full DD may already be locked for collection despite a recent manual payment.
    near_collection = 0 <= (collection - today).days <= 7
    if mode == 'full' and confirmed and expected is None and near_collection:
        reserve = max(reserve, bill['balance'])
    available = money(observed.get('balances', {}).get(value['paying_account']))
    cash_gap = max(ZERO, reserve - available) if available is not None else None
    if observed.get('funding_complete'):
        other_bills = sum((money(e['amount'], ZERO) for e in observed.get('costs', []) if today <= day(e['date']) <= max(today, due)), ZERO)
        everyday = money(observed.get('daily'), ZERO) * max(0, (due - today).days)
        protected = money(observed.get('buffer'), ZERO)
        total_cash = sum((money(v, ZERO) for v in observed.get('balances', {}).values()), ZERO)
        cash_gap = max(cash_gap or ZERO, reserve + other_bills + everyday + protected - total_cash, ZERO)
    elif reserve:
        result['warnings'].append('Amex: funds for bills and repayment could not be verified.')
        result['valid'] = False
    if reserve and result['current'] is not None and reserve > max(ZERO, result['current']):
        result['warnings'].append('Amex: protected collection exceeds the current card balance. Confirm the collection amount before forecasting.')
        result['valid'] = False
    days = (due - today).days
    if remaining and days < 0:
        result['warnings'].append(f'Amex: £{remaining:,.2f} unconfirmed after {due:%d %b}. Check payment now.')
    elif remaining and days <= 7 and (scheduled is None or scheduled < remaining or cash_gap is None or cash_gap > 0 or not fresh):
        suffix = 'today' if days == 0 else f'in {days} days'
        result['warnings'].append(f'Amex: £{remaining:,.2f} still unpaid; due {suffix} ({due:%d %b}).')
    if cash_gap:
        result['warnings'].append(f'Amex: {value["paying_account"]} is £{cash_gap:,.2f} short after reserving repayment and other costs.')
    if remaining and mode == 'fixed' and scheduled is not None and scheduled < remaining:
        result['warnings'].append(f'Amex: fixed Direct Debit leaves £{remaining - scheduled:,.2f} of the statement uncovered.')
    if remaining and mode == 'minimum':
        result['warnings'].append('Amex: minimum payment does not ensure the full statement is paid.')
    if near_collection and mode not in ('none', 'unknown') and (remaining or confirmed):
        result['dd_caution'] = 'Check Amex before extra payments within four working days of collection; both payments may be taken.'
    if mode == 'full' and confirmed and expected is None and near_collection:
        result['warnings'].append('Amex: confirm the Direct Debit amount after a repayment; both may be taken.')
        result['valid'] = False
    if value['carried_balance'] == 'yes' or observed.get('interest_seen'):
        result['warnings'].append('Amex: a balance was carried forward; residual interest may follow payment.')
    manually_settled = manual >= bill['balance'] and through and today - timedelta(days=1) <= through <= today
    if (not fresh or not observed.get('amex_ok')) and not manually_settled:
        result['warnings'].append('Amex: payment confirmation is stale or incomplete. Refresh bank data.')
        result['valid'] = False
    if day(observed.get('from')) and day(observed['from']) > bill['date'] + timedelta(days=1) and manual < bill['balance']:
        result['warnings'].append('Amex: transaction coverage misses part of this statement period; confirm repayments manually.')
        result['valid'] = False
    if bill['date'] < today - timedelta(days=62):
        result['warnings'].append('Amex: this statement is old. Enter or retrieve the latest statement.')
        result['valid'] = False
    result.update(confirmed=confirmed, remaining=remaining, scheduled=scheduled, reserve=reserve,
                  cash_gap=cash_gap, collection=collection, days=days,
                  coverage='Confirmed payments' if remaining == 0 else 'Direct Debit planned, funds available' if scheduled is not None and scheduled >= remaining and cash_gap == 0 and fresh else 'Action needed')
    return result


def protected_events(events, assessment, today, horizon):
    """Replace only this cycle's Amex cost, avoiding an extra £50 plus full statement."""
    if not assessment['enabled'] or not assessment['statement']:
        return events
    due = assessment['statement']['due']
    from finance.test_forecast import is_amex
    rows = [e for e in events if not (is_amex(e['name']) and e['date'] <= max(today, due))]
    if assessment['reserve'] > 0 and max(today, due) <= today + timedelta(days=horizon):
        rows.append({'name': 'Amex statement repayment', 'date': max(today, min(due, assessment.get('collection', due))), 'amount': assessment['reserve'],
                     'basis': 'Protected unpaid statement; not a payment confirmation', 'category': 'repayment',
                     'undated': False, 'amex_statement_protection': True})
    return sorted(rows, key=lambda row: row['date'])


def print_status(printer, left, line, assessment, *, detailed=False):
    if not assessment['enabled'] or (not detailed and not assessment['warnings']):
        return
    from receipt.output import heading
    line(printer, '-')
    printer.set(bold=True)
    heading(printer, 'AMEX PAYMENT CHECK', write=left)
    printer.set(bold=False)
    bill = assessment['statement']
    if detailed and bill:
        for label, number in [('Statement balance', bill['balance']), ('Confirmed repayments', assessment['confirmed']),
                              ('Still to pay', assessment['remaining']), ('Protected for repayment', assessment['reserve'])]:
            left(printer, f'{label}: £{number:,.2f}')
        left(printer, f'Statement {bill["date"]:%d %b}; due {bill["due"]:%d %b %Y}')
        left(printer, f'Direct Debit: {assessment["config"]["dd_mode"]}')
        if assessment['scheduled'] is not None:
            left(printer, f'Expected collection: £{assessment["scheduled"]:,.2f}')
        left(printer, assessment['coverage'])
        if assessment.get('dd_caution'):
            left(printer, assessment['dd_caution'])
    for warning in assessment['warnings'][:3] if not detailed else assessment['warnings']:
        left(printer, warning)
    line(printer, '-')
