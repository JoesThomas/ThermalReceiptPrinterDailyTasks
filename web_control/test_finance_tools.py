"""Explicit manual generation/printing, separate from scheduled and live previews."""
from datetime import datetime, timezone
from decimal import Decimal
from flask import abort, flash, redirect, render_template, request, session, url_for
from receipt.local_time import uk_today
from finance.test_receipt import build, receipt, validate


def collect(values, today):
    from finance.receipt import load_finance_settings
    from finance.projection import build_projection, money
    from finance.commitments import repayment_commitments
    from services.subscriptions import load_subscriptions
    settings = load_finance_settings().copy()
    subscriptions = load_subscriptions()
    daily = values.get('daily_spend', '').strip()
    cash = values.get('opening_cash', '').strip()
    daily_value, cash_value = money(daily), money(cash)
    if daily and (daily_value is None or not 0 <= daily_value <= 100000):
        raise ValueError('Enter a valid daily spending estimate.')
    if cash and (cash_value is None or not 0 <= cash_value <= 10000000):
        raise ValueError('Enter valid starting bank cash.')
    if daily:
        settings['runway_daily_spend'] = str(daily_value)
    if cash and daily:
        # A fully manual scenario reads local commitments without touching APIs.
        transactions = []
        balances = {'HSBC': {'available': cash_value}, 'MONZO': {'available': Decimal(0)}}
        status = {'monthly': subscriptions.get('monthly', []) + repayment_commitments(subscriptions, settings),
                  'yearly': subscriptions.get('yearly', [])}
        coverage = 'complete'
    else:
        try:
            from services import live_pipeline as pipeline
        except RuntimeError:
            raise ValueError('Configure bank connections, or enter both starting cash and daily spending for a manual estimate.') from None
        from services.finance_source import collect as collect_source, FinanceDependencies
        from dataclasses import fields
        from concurrent.futures import ThreadPoolExecutor
        dependencies = FinanceDependencies(**{field.name: (lambda: today) if field.name == "today"
            else getattr(pipeline, field.name) for field in fields(FinanceDependencies)})
        with ThreadPoolExecutor(max_workers=2) as pool:
            data_future = pool.submit(collect_source, dependencies, persist=False)
            balance_future = pool.submit(pipeline.get_account_balances)
            try: data = data_future.result()
            except Exception: data = ([], [], [], [], {'bank_data_status': 'unavailable'})
            try: balances = balance_future.result()
            except Exception: balances = {}
        transactions = data[0]
        status = pipeline.build_subscription_status(transactions, subscriptions_data=subscriptions, finance_settings=settings, today=today)
        coverage = data[4].get('bank_data_status', 'unavailable')
        if cash:
            balances = dict(balances, HSBC={'available': cash_value}, MONZO={'available': Decimal(0)})
    projection = build_projection(balances, transactions, status['monthly'], status['yearly'], settings, today, bank_status=coverage)
    if cash: projection['warnings'].append('Starting cash is a manual scenario input, not a bank balance update.')
    if daily: projection['warnings'].append('Everyday spending uses the manual daily estimate.')
    if cash and daily: projection['warnings'].append('No bank lookup or payment matching was performed; local commitments are assumed outstanding.')
    from finance.salary_plan import reserves
    projection['reserve_details'] = reserves(settings)
    projection['repayment_options'] = [dict(item) for item in subscriptions.get('instalments', []) + settings.get('debts', [])]
    card = balances.get('AMEX', {}).get('current')
    if card is not None and not any('amex' in str(item.get('name', '')).lower() for item in projection['repayment_options']):
        projection['repayment_options'].append({'name': 'Amex', 'balance': abs(Decimal(str(card))), 'type': 'credit_card'})
    return projection


def register(app, login_required, start_print):
    @app.get('/finance/test')
    @login_required
    def test_finance_page():
        from receipt.archive import load
        text = None
        identifier = session.get('test_finance_receipt')
        if identifier:
            try:
                item = load(identifier)
                candidate = item['pages'].get('finance', '')
                if 'SIMULATION - POTENTIAL SALARY' in candidate: text = candidate
            except ValueError: pass
        from finance.receipt import load_finance_settings
        defaults = {'savings_target': str(load_finance_settings().get('salary_savings_target') or 0)}
        return render_template('test_finance.html', today=uk_today(), result_text=text, values=defaults)

    @app.post('/finance/test/generate')
    @login_required
    def generate_test_finance():
        today = uk_today()
        values = request.form.to_dict()
        try:
            validate(values, today)
            projection = collect(values, today)
            result = build(projection, values, today)
            text = receipt(result, today)
            from receipt.archive import save
            identifier = save({'finance': text}, {}, datetime.now(timezone.utc).isoformat(), 'preview', {})
            session['test_finance_receipt'] = identifier
            flash('Test receipt generated privately. Nothing has been sent to the printer.')
            return redirect(url_for('test_finance_page'))
        except (ValueError, OSError, TypeError) as error:
            # Validation messages are local; provider failures are handled in collect.
            return render_template('test_finance.html', today=today, result_text=None, values=values, error=str(error)), 400

    @app.post('/finance/test/print')
    @login_required
    def print_test_finance():
        from receipt.archive import load
        identifier = session.get('test_finance_receipt')
        if not identifier: abort(400)
        try: item = load(identifier)
        except ValueError: abort(404)
        if 'SIMULATION - POTENTIAL SALARY' not in item['pages'].get('finance', ''): abort(400)
        started, error = start_print(['--archive', identifier, 'finance'])
        flash('Test finance receipt queued.' if started else error)
        return redirect(url_for('test_finance_page'))
