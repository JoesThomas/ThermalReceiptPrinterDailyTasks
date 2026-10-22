"""Organiser and cash-pot screens backed by the existing finance calculations."""
from datetime import date, timedelta
from pathlib import Path
import secrets
from time import time
from flask import abort, flash, redirect, render_template, request, session, url_for
from organiser import records, vault
from finance import annual_funds as funds
from finance.money import parse, ZERO
from receipt.local_time import uk_today

ROOT = Path(__file__).resolve().parents[1]


def financial_view():
    value = funds.store().read()
    result = {'settings': value, 'fund_plan': funds.plan(ZERO, valid=False), 'safe': None, 'per_day': None,
              'observed_daily': None, 'transactions': [], 'upcoming': [], 'error': None, 'checked_at': None}
    from web_control.finance_refresh import FinanceRefresh
    manager = FinanceRefresh(ROOT)
    snapshot = manager.read()
    if not snapshot or not manager.fresh(snapshot):
        result['error'] = 'Refresh Finance review before relying on available money or recording a suggested transfer.'
        return result
    try:
        from services.live_pipeline import build_subscription_status
        from finance.receipt import load_finance_settings
        from finance.projection import build_projection
        from finance.salary_plan import build
        today = uk_today()
        transactions, _, _, _, summary = snapshot['data']
        settings = load_finance_settings()
        status = build_subscription_status(transactions, today=today)
        projection = build_projection(snapshot['balances'], transactions, status['monthly'], status['yearly'], settings, today,
                                      bank_status=summary.get('bank_data_status', 'unavailable'))
        allocation = build(summary.get('salary_incomings', []), transactions, snapshot['balances'], projection, settings, None, today)
        plan = allocation['fund_plan']
        safe = max(ZERO, projection['safe_before_payday'] - plan['total']) if projection['valid'] and projection.get('safe_before_payday') is not None and plan['valid'] else None
        result.update(fund_plan=plan, safe=safe, per_day=safe / (projection['payday'] - today).days if safe is not None else None,
                      observed_daily=projection['daily'], transactions=transactions, upcoming=projection['upcoming'], checked_at=snapshot['checked_at'])
        if not projection['valid']:
            result['error'] = 'Complete balances, repayment assumptions and spending coverage are required. Review Finance warnings.'
    except (ValueError, OSError, KeyError, RuntimeError):
        result['error'] = 'The finance plan could not be verified. Refresh Finance and check local settings.'
    return result


def daily_financial_lines(today=None):
    today = today or uk_today()
    value = funds.store().read()
    if not value['enabled']:
        return []
    lines = []
    for row in funds.pots(value, today):
        gap = max(ZERO, row['target'] - row['balance'])
        days = (date.fromisoformat(row['due']) - today).days
        if gap and (days <= 7 or (today.weekday() == 6 and days <= 30)):
            lines.append(f"{row['name']}: £{gap:,.2f} still needed by {date.fromisoformat(row['due']):%d %b}.")
    result = financial_view()
    if result['safe'] is not None:
        lines.append(f"Until payday: £{result['safe']:,.2f} available / £{result['per_day']:,.2f} per day (estimate).")
        if result['observed_daily'] > result['per_day']:
            lines.append('Recent spending pace is above this daily budget.')
    if today.weekday() == 6:
        for row in result['upcoming']:
            if row['date'] <= today + timedelta(days=7) and row['amount'] >= 100:
                lines.append(f"Upcoming: {row['name']} £{row['amount']:,.2f} on {row['date']:%d %b}.")
                if len(lines) >= 7:
                    break
    return lines[:7]


def register(app, login_required):
    @app.context_processor
    def context():
        return {'life_planning_available': True}

    @app.get('/organiser')
    @login_required
    def organiser_page():
        value = records.store().read()
        documents, error = [], None
        if 0 <= time() - session.get('document_unlocked_at', 0) < 900:
            try:
                documents = vault.listing()
            except (ValueError, OSError):
                error = 'Documents are unavailable; check the separate key and document storage.'
        from web_control.today_summary import read, CALENDAR
        calendar = read(CALENDAR)
        return render_template('organiser.html', organiser=value, kinds=records.KINDS, documents=documents, document_error=error,
                               clashes=records.clashes(calendar.get('events', []), value['travel_buffer']), calendar_checked=calendar.get('checked_at'), today=uk_today())

    @app.post('/organiser/item')
    @login_required
    def organiser_save():
        try:
            identifiers = request.form.getlist('document_id')
            if identifiers:
                if not 0 <= time() - session.get('document_unlocked_at', 0) < 900:
                    abort(403)
                if not set(identifiers) <= {r['id'] for r in vault.listing()}:
                    raise ValueError('Choose current documents from unlocked storage.')
            identifier = request.form.get('id') or None
            # Retain existing links when editing an item while storage is locked.
            if identifier and not identifiers:
                before = next((r for r in records.store().read()['items'] if r['id'] == identifier), None)
                if before and before['documents'] and request.form.get('clear_documents') != 'on':
                    form = request.form.copy()
                    form.setlist('document_id', before['documents'])
                else:
                    form = request.form
            else:
                form = request.form
            records.save_item(form, identifier)
            flash('Organiser item saved locally.')
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Organiser could not be saved.')
        return redirect(url_for('organiser_page'))

    @app.post('/organiser/<identifier>/<action>')
    @login_required
    def organiser_action(identifier, action):
        try:
            records.update(identifier, action, request.form.get('due'))
        except (ValueError, OSError):
            abort(400)
        return redirect(url_for('organiser_page'))

    @app.post('/organiser/travel')
    @login_required
    def organiser_travel():
        try:
            records.store().update(lambda value: value.update(travel_buffer=int(request.form.get('minutes', '30'))))
        except (ValueError, OSError):
            abort(400)
        return redirect(url_for('organiser_page'))

    @app.get('/finance/funds')
    @login_required
    def annual_funds_page():
        result = financial_view()
        candidates = funds.bank_candidates(result['transactions'])
        return render_template('annual_funds.html', fund_view=result, candidates=candidates, today=uk_today())

    @app.post('/finance/funds/settings')
    @login_required
    def annual_funds_settings():
        try:
            def change(value):
                value.update(enabled=request.form.get('enabled') == 'on', tax_enabled=request.form.get('tax_enabled') == 'on',
                             tax_source=request.form.get('tax_source', 'rental'), tax_inside=request.form.get('tax_inside') == 'on',
                             tax_destination=request.form.get('tax_destination', 'Tax reserve').strip(), tax_bill_name=request.form.get('tax_bill_name', '').strip())
                for name in ('tax_target', 'tax_paid', 'tax_balance'):
                    amount = parse(request.form.get(name, '0'))
                    if amount is None or amount < 0:
                        raise ValueError('Enter valid tax amounts.')
                    value[name] = str(amount)
                value['tax_due'] = request.form.get('tax_due', '').strip()
                value['tax_checked'] = request.form.get('tax_checked', '').strip()
                if value['tax_checked'] and date.fromisoformat(value['tax_checked']) > uk_today():
                    raise ValueError('Estimate check date cannot be in the future.')
            funds.store().update(change)
            flash('Tax and annual funding settings saved. No transfers have been made.')
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Fund settings could not be saved.')
        return redirect(url_for('annual_funds_page'))

    @app.post('/finance/funds/pot')
    @login_required
    def annual_pot_save():
        try:
            identifier = request.form.get('id') or secrets.token_hex(12)
            row = {'id': identifier, 'name': request.form.get('name', '').strip(), 'destination': request.form.get('destination', '').strip(),
                   'target': str(parse(request.form.get('target'))), 'balance': str(parse(request.form.get('balance'))),
                   'bill_name': request.form.get('bill_name', '').strip(), 'due': request.form.get('due', ''), 'inside': request.form.get('inside') == 'on', 'priority': int(request.form.get('priority', '1'))}
            def change(value):
                index = next((i for i, r in enumerate(value['pots']) if r['id'] == identifier), None)
                if index is not None:
                    value['pots'][index] = row
                else:
                    value['pots'].append(row)
            funds.store().update(change)
        except (ValueError, OSError):
            flash('Enter a pot name, target, balance, deadline and priority.')
        return redirect(url_for('annual_funds_page'))

    @app.post('/finance/funds/<identifier>/delete')
    @login_required
    def annual_pot_delete(identifier):
        try:
            def change(value):
                if any(t['pot'] == identifier and t['status'] == 'completed' for t in value['transfers']):
                    raise ValueError('Match pending transfers before removing this pot.')
                value['pots'] = [r for r in value['pots'] if r['id'] != identifier]
            funds.store().update(change)
        except (ValueError, OSError) as error:
            flash(str(error))
        return redirect(url_for('annual_funds_page'))

    @app.post('/finance/funds/complete')
    @login_required
    def annual_fund_complete():
        result = financial_view()
        row = next((r for r in result['fund_plan']['rows'] if r['transfer_id'] == request.form.get('transfer_id')), None)
        if not result['fund_plan']['valid'] or not row or row['suggested'] <= 0:
            abort(409, description='The plan changed or bank data is stale. Refresh before recording the transfer.')
        try:
            funds.complete(row['transfer_id'], row['id'], row['suggested'])
        except (ValueError, OSError):
            abort(400)
        flash('Transfer recorded once. External transfers remain reserved until matched to a posted bank debit.')
        return redirect(url_for('annual_funds_page'))

    @app.post('/finance/funds/match')
    @login_required
    def annual_fund_match():
        if request.form.get('confirm_destination') != 'on':
            abort(400)
        result = financial_view()
        if result['error']:
            abort(409)
        try:
            funds.match(request.form.get('transfer_id'), request.form.get('bank_key'), result['transactions'])
        except (ValueError, OSError):
            abort(400)
        return redirect(url_for('annual_funds_page'))
