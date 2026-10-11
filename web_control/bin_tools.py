import json
from datetime import timedelta
from flask import flash, redirect, render_template, request, url_for
from services import bin_collections as bins
from receipt.local_time import uk_receipt_time


def register(app, login_required):
    def display(choices=None, code='', manual_draft=None):
        try: state=bins.load()
        except ValueError as error:
            flash(str(error));state=dict(bins.DEFAULT)
        return render_template('bins.html',bins=state,choices=choices or [],lookup_postcode=code,
                               checked=uk_receipt_time(state.get('last_success')),
                               manual=manual_draft if manual_draft is not None else bins.manual_text(state['manual']),
                               tomorrow=bins.due_on(state,bins.today()+timedelta(days=1)))

    @app.get('/bins')
    @login_required
    def bin_settings(): return display()

    @app.post('/bins/lookup')
    @login_required
    def bin_address_lookup():
        try:
            code=bins.postcode(request.form.get('postcode',''))
            return display(bins.addresses(code),code)
        except (ValueError,bins.requests.RequestException):
            flash('Address lookup unavailable. Enter the address, postcode and UPRN below. Your saved address was kept.')
            return redirect(url_for('bin_settings'))

    @app.post('/bins/save')
    @login_required
    def bin_settings_save():
        try:
            choice=json.loads(request.form['choice']) if 'choice' in request.form else None
            if choice is not None and not isinstance(choice,dict): raise ValueError('Choose a valid address.')
            bins.configure(request.form.get('enabled')=='on',request.form.get('provider','birmingham'),
                           choice.get('address','') if choice else request.form.get('address',''),
                           request.form.get('postcode',''),
                           choice.get('uprn','') if choice else request.form.get('uprn',''),
                           bins.parse_manual(request.form.get('manual','')))
            state=bins.refresh(force=True)
            flash('Bin settings saved.' + (' Council check failed; see the status below.' if state.get('error') else ''))
        except (ValueError,TypeError) as error: flash(str(error))
        return redirect(url_for('bin_settings'))

    @app.post('/bins/manual')
    @login_required
    def bin_manual_save():
        try:
            rows = bins.parse_manual(request.form.get('manual', ''))
            if not rows:
                raise ValueError('Enter at least one manual collection date.')
            with bins.transaction() as state:
                state.update(provider='manual', manual=rows,
                             enabled=request.form.get('enabled') == 'on',
                             collections=[], last_success='', last_attempt='', error='')
            flash('Manual schedule saved and selected.')
        except (ValueError, TypeError) as error:
            flash(str(error))
            return display(manual_draft=request.form.get('manual', ''))
        return redirect(url_for('bin_settings'))

    @app.post('/bins/refresh')
    @login_required
    def bin_schedule_refresh():
        try:
            state=bins.refresh(force=True)
            flash(state.get('error') or 'Bin schedule checked.')
        except ValueError as error: flash(str(error))
        return redirect(url_for('bin_settings'))
