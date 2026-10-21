"""Detect posted Amex interest and retain warnings until explicitly acknowledged."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / 'data' / 'amex_interest_alerts.json'


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('charges'), dict):
        raise ValueError('Invalid Amex interest alerts.')
    for key, row in value['charges'].items():
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key) or not isinstance(row, dict):
            raise ValueError('Invalid Amex interest charge.')
        date.fromisoformat(row['date'])
        if not isinstance(row['amount'], str) or not re.fullmatch(r'\d+\.\d{2}', row['amount']):
            raise ValueError('Invalid Amex interest amount.')
        try:
            amount = Decimal(row['amount'])
        except (InvalidOperation, TypeError):
            raise ValueError('Invalid Amex interest amount.') from None
        if not amount.is_finite() or amount <= 0 or row['currency'] not in {'GBP', 'EUR', 'USD', 'AUD'} or type(row['acknowledged']) is not bool:
            raise ValueError('Invalid Amex interest amount.')


def store(path=None):
    return PrivateStore(path or FILE, default=lambda: {'version': 1, 'charges': {}}, validate=validate)


def detect(transactions, today=None):
    """Use source identity, debit direction and category/charge wording, never merchant alone.

    Card amounts are positive for debits in TrueLayer. An explicit transaction type
    takes precedence, including installations with older signed amount fixtures.
    Request-specific transaction_id is deliberately not used for deduplication.
    """
    today = today or datetime.now(ZoneInfo('Europe/London')).date()
    charges = {}
    occurrences = {}
    seen_request_ids = set()
    for tx in transactions:
        if not isinstance(tx, dict) or str(tx.get('_source_provider', '')).upper() != 'AMEX':
            continue
        kind = str(tx.get('transaction_type', '')).upper()
        try:
            amount = Decimal(str(tx.get('amount')))
            if not amount.is_finite() or not amount or kind in {'CREDIT', 'REFUND'}:
                continue
            if kind != 'DEBIT' and (kind or amount < 0):
                continue
            amount = abs(amount).quantize(Decimal('.01'))
            if amount <= 0:
                continue
            on = date.fromisoformat(str(tx.get('timestamp') or tx.get('date'))[:10])
        except (ValueError, TypeError, InvalidOperation):
            continue
        currency = str(tx.get('currency') or 'GBP').upper()
        if currency not in {'GBP', 'EUR', 'USD', 'AUD'} or on > today:
            continue
        description = ' '.join(str(tx.get('description') or '').upper().split())
        if re.search(r'\b(REFUND|REVERSAL|REVERSED|WAIVED|INTEREST[- ]FREE|NO INTEREST)\b', description):
            continue
        category = str(tx.get('transaction_category', '')).upper()
        wording = re.fullmatch(r'(?:AMEX |AMERICAN EXPRESS )?(?:(?:PURCHASE|CASH|DEBIT|BALANCE TRANSFER) )?INTEREST(?: CHARGE(?:D)?)?(?: ON (?:PURCHASES|CASH ADVANCES))?(?: [\d./ -]+)?', description)
        if category != 'INTEREST' and not wording:
            continue
        # Scope identities to cards; hash rather than retain account/card identifiers.
        account = str(tx.get('_source_account') or '')
        request_id = tx.get('transaction_id')
        if request_id:
            request_key = (account, str(request_id))
            if request_key in seen_request_ids:
                continue
            seen_request_ids.add(request_key)
        stable = tx.get('normalised_provider_transaction_id') or tx.get('provider_transaction_id')
        fingerprint = json.dumps([account, on.isoformat(), str(amount), currency, description])
        ordinal = occurrences.get(fingerprint, 0)
        occurrences[fingerprint] = ordinal + 1
        identity = json.dumps([account, str(stable)]) if stable else fingerprint + ':' + str(ordinal)
        key = hashlib.sha256(identity.encode()).hexdigest()
        charges[key] = {'date': on.isoformat(), 'amount': str(amount), 'currency': currency, 'acknowledged': False}
    return charges


def capture(transactions, *, path=None, today=None):
    charges = detect(transactions, today)
    if charges:
        def change(value):
            for key, row in charges.items():
                previous = value['charges'].get(key, {})
                unchanged = all(previous.get(field) == row[field] for field in ('date', 'amount', 'currency'))
                value['charges'][key] = {**row, 'acknowledged': bool(unchanged and previous.get('acknowledged', False))}
        store(path).update(change)


def pending(*, path=None):
    return visible(path=path)


def visible(transactions=(), *, path=None, today=None):
    """Merge fresh evidence without resurrecting acknowledged historical charges."""
    saved = store(path).read()['charges']
    rows = {**saved}
    for key, row in detect(transactions, today).items():
        if key not in saved:
            rows[key] = row
    return [{'id': key, **row} for key, row in sorted(rows.items(), key=lambda item: item[1]['date'], reverse=True) if not row['acknowledged']]


def acknowledge(identifiers, *, path=None):
    # Only acknowledge rows actually shown; a concurrent new charge stays visible.
    def change(value):
        for key in identifiers:
            if key in value['charges']:
                value['charges'][key]['acknowledged'] = True
    store(path).update(change)


def receipt_warning(printer, left, line, charges):
    if not charges:
        return
    from receipt.output import heading
    line(printer, '-')
    printer.set(bold=True)
    heading(printer, 'AMEX INTEREST ALERT', write=left)
    printer.set(bold=False)
    for row in charges[:3]:
        on = date.fromisoformat(row['date']).strftime('%d %b %Y')
        symbol = '£' if row['currency'] == 'GBP' else row['currency'] + ' '
        left(printer, f"{on}: {symbol}{Decimal(row['amount']):,.2f} interest charged")
    if len(charges) > 3:
        left(printer, f'{len(charges) - 3} more charges in the web app.')
    left(printer, 'Review your Amex statement. Acknowledge in app.')
    line(printer, '-')
