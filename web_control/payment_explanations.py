"""Private category/match explanations and a bounded correction history."""
from datetime import datetime, timezone
from pathlib import Path
from flask import render_template
from storage import PrivateStore
from finance_trends import categorise_transaction, _normalise_merchant, _parse_date, _amount
from web_control.payments import external_payments
FILE = Path(__file__).resolve().parents[1] / 'data' / 'finance_explanations.json'


def store():
    def validate(value):
        if not isinstance(value, dict) or any(not isinstance(value.get(key, []), list) for key in ('payments','commitments','audit','price_changes')): raise ValueError('Invalid payment explanation history')
    return PrivateStore(FILE, default=lambda: {'payments': [], 'commitments': [], 'audit': [], 'price_changes': []}, validate=validate)


def basis(tx, rules, private):
    merchant = _normalise_merchant(str(tx.get('merchant_name') or tx.get('merchant') or tx.get('description') or ''))
    for rule in rules.get('transactions', []):
        if not isinstance(rule, dict): continue
        try:
            if _parse_date(tx).isoformat() == rule['date'] and abs(_amount(tx)-abs(float(rule['amount']))) <= .005 and _normalise_merchant(rule.get('merchant','')) and _normalise_merchant(rule['merchant']) in merchant:
                return 'Manual correction: matching date, amount and merchant'
        except (AttributeError,KeyError,TypeError,ValueError): continue
    for needle in rules:
        if needle == 'transactions': continue
        import re
        token = _normalise_merchant(needle)
        matches = bool(re.search(r'\bRENT\b', merchant)) if token == 'RENT' else bool(token and token in merchant)
        if matches: return 'Manual merchant rule' if needle in private else 'Built-in merchant rule'
    return 'Bank category mapped to an app category' if categorise_transaction(tx, rules) != 'OTHER' else 'No recognised rule or bank category; review needed'


def capture(transactions, rows, today, rules, private):
    payments = []
    external = external_payments(transactions)
    for tx in external:
        on = _parse_date(tx)
        if not on or not 0 <= (today-on).days <= 29: continue
        payments.append({'date': on.isoformat(), 'merchant': str(tx.get('merchant_name') or tx.get('merchant') or tx.get('description') or '')[:160], 'amount': round(_amount(tx),2), 'category': categorise_transaction(tx,rules), 'basis': basis(tx,rules,private)})
    commitments = []; price_changes = []
    for row in rows:
        item, tx = row['item'], row.get('transaction')
        commitments.append({'name': item['name'], 'amount': item['amount'], 'paid': bool(tx), 'basis': ('Bank debit matched the existing repayment date/amount checks (up to two days tolerance)' if row.get('method') == 'Payment date and amount' else 'Bank debit matched the configured merchant and amount checks') if tx else 'No bank match; a file entry alone does not prove payment', 'date': str(_parse_date(tx)) if tx else ''})
        if item.get('category', 'subscription') != 'subscription': continue
        terms = [str(term).casefold() for term in item.get('match',[]) if str(term).strip()]
        if not terms: continue
        candidates = [tx for tx in external if _parse_date(tx) and 0 <= (today-_parse_date(tx)).days <= 60 and any(term in str(tx.get('spend_description') or tx.get('description') or '').casefold() for term in terms)]
        candidates.sort(key=lambda tx: _parse_date(tx))
        if len(candidates) < 2: continue
        first, last = candidates[-2:]
        if (_parse_date(last)-_parse_date(first)).days >= 20 and _amount(last) > _amount(first) + .005:
            price_changes.append({'name': item['name'], 'previous': round(_amount(first),2), 'current': round(_amount(last),2), 'date': _parse_date(last).isoformat()})
    store().update(lambda value: value.update(payments=payments[:1000], commitments=commitments, price_changes=price_changes, checked_at=datetime.now(timezone.utc).isoformat()))


def correction(payment, category, scope):
    def change(value):
        rows = value.setdefault('audit', [])
        rows.append({'at': datetime.now(timezone.utc).isoformat(), 'date': payment['date'], 'merchant': payment['merchant'], 'amount': payment['amount'], 'category': category, 'scope': scope})
        value['audit'] = rows[-300:]
    store().update(change)


def register(app, login_required):
    @app.get('/finance/explanations')
    @login_required
    def payment_trail():
        from receipt.local_time import uk_receipt_time
        value = store().read()
        return render_template('payment_explanations.html', explanations=value, checked=uk_receipt_time(value.get('checked_at')))
