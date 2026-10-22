"""Local statement/DD inputs and read-only warnings; no payments are initiated."""
from datetime import date
from flask import flash, redirect, request, session, url_for
from finance import amex_protection as protection
from finance.projection import money, day


def view():
    try:
        result = protection.assess()
        result['error'] = None
        return result
    except (ValueError, OSError):
        return {'enabled': False, 'valid': False, 'warnings': ['Amex payment protection unavailable; check private data.'],
                'config': protection.defaults(), 'error': 'Amex payment protection could not be read.'}


def register(app, login_required):
    @app.context_processor
    def context():
        return {'amex_protection': view()} if session.get('authenticated') else {}

    @app.post('/finance/amex-protection')
    @login_required
    def save_amex_protection():
        try:
            def change(value):
                value.update(enabled=request.form.get('enabled') == 'on', source=request.form.get('source', 'auto'),
                             dd_mode=request.form.get('dd_mode', 'unknown'), paying_account=request.form.get('paying_account', 'HSBC'),
                             carried_balance=request.form.get('carried_balance', 'unknown'))
                fields = {name: request.form.get(name, '').strip() for name in ('statement_date', 'statement_balance', 'due_date')}
                if any(fields.values()):
                    bill = protection.statement({'date': fields['statement_date'], 'balance': fields['statement_balance'], 'due': fields['due_date']})
                    if not bill or bill['date'] > protection.uk_today():
                        raise ValueError('Enter a valid statement date, balance and due date.')
                    value['manual_statement'] = {'date': bill['date'].isoformat(), 'due': bill['due'].isoformat(), 'balance': str(bill['balance'])}
                else:
                    value['manual_statement'] = {}
                dd_text = request.form.get('dd_amount', '').strip()
                dd = money(dd_text)
                if dd_text and (dd is None or dd < 0):
                    raise ValueError('Enter a valid expected Direct Debit amount.')
                value['dd_amount'] = str(dd) if dd_text else None
                dd_date = request.form.get('dd_date', '').strip()
                value['dd_date'] = date.fromisoformat(dd_date).isoformat() if dd_date else None
                if value['dd_mode'] == 'fixed' and dd is None:
                    raise ValueError('Enter your fixed Direct Debit amount.')
                # The entered total is an alternative confirmation source, never added to bank credits.
                paid_text = request.form.get('confirmed_total', '0').strip() or '0'
                paid = money(paid_text)
                bill_source = value['manual_statement'] if value['source'] == 'manual' else value['evidence'].get('statement', {})
                bill = protection.statement(bill_source)
                if paid is None or paid < 0 or (paid > 0 and (not bill or paid > bill['balance'])):
                    raise ValueError('Confirmed repayments must be between zero and the statement balance.')
                through = request.form.get('confirmed_through', '').strip()
                if paid > 0 and (not day(through) or not bill['date'] < day(through) <= protection.uk_today()):
                    raise ValueError('Enter the date through which Amex has confirmed these repayments.')
                value.update(confirmed_total=str(paid), confirmed_statement=bill['date'].isoformat() if bill else None,
                             confirmed_through=date.fromisoformat(through).isoformat() if through else None)
                protection.validate(value)
            protection.store().update(change)
            flash('Amex payment protection saved. No bank payment or Direct Debit setting was changed.')
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Amex payment protection could not be saved.')
        return redirect(url_for('finance_review') + '#amex-payment-protection')
