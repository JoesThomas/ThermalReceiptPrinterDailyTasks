"""Account selection and direct correction/recovery entry points."""
from flask import abort,flash,redirect,render_template,request,url_for


def register(app,login_required):
    @app.post('/receipt/selected-print')
    @login_required
    def print_selected_sections():
        from receipt.selection import validate
        try: sections=validate(request.form.getlist('sections'))
        except ValueError: abort(400)
        # Reuse the normal job mutex, timeout and progress reporting.
        from flask import current_app
        start=current_app.config['SELECTED_PRINT_START']
        started,error=start(['--pages',*sections])
        flash('Selected receipt sections started.' if started else error)
        return redirect(url_for('preview',source='printed',sections=','.join(sections)))

    @app.get('/diagnostics/download')
    @login_required
    def diagnostic_download():
        import json
        from flask import Response
        from web_control.diagnostics import export
        response = Response(json.dumps(export(), indent=2), mimetype='application/json')
        response.headers['Content-Disposition'] = 'attachment; filename="receipt-diagnostics.json"'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/finance/accounts')
    @login_required
    def cash_accounts():
        from finance import bank_accounts
        try: selected=bank_accounts.selection();error=None
        except (ValueError,OSError,TypeError): selected={};error='Saved account selection could not be loaded.'
        state=bank_accounts.catalog();accounts=state['accounts'];seen=set()
        for row in accounts:
            provider=row['provider']
            row['included']=row['id'] in selected[provider] if provider in selected else provider not in seen
            seen.add(provider)
        return render_template('cash_accounts.html',accounts=accounts,checked=state.get('checked_at'),error=error)

    @app.post('/finance/accounts')
    @login_required
    def save_cash_accounts():
        from finance import bank_accounts
        from storage import write_json
        try:
            if request.form.get('mode')=='defaults': write_json(bank_accounts.SELECTION,{})
            else: bank_accounts.choose({p:request.form.getlist(p) for p in bank_accounts.PROVIDERS})
            flash('Cash account selection saved privately. Refresh Finance or generate a new receipt to use it.')
        except (ValueError,OSError,TypeError,KeyError): flash('Choose valid accounts from the last bank check, or reset to defaults after reconnecting.')
        return redirect(url_for('cash_accounts'))

    @app.get('/corrections')
    @login_required
    def corrections(): return render_template('corrections.html')

    @app.post('/calendar/location')
    @login_required
    def calendar_location():
        from services.calendar_locations import save
        try:
            save(request.form.get('id',''),None if request.form.get('reset') else request.form.get('location',''))
            flash('Local calendar location correction saved. The external calendar is unchanged.')
        except (ValueError,OSError): flash('Use a valid event and a location up to 500 characters.')
        return redirect(url_for('calendar_map'))

    @app.get('/receipts/latest')
    @login_required
    def latest_receipt():
        from receipt import archive
        for path in sorted(archive.DIRECTORY.glob('*.json'),reverse=True):
            try: item=archive.load(path.stem)
            except ValueError: continue
            return redirect(url_for('archive_detail',identifier=item['id']))
        flash('No saved receipt yet. Generate a preview or print a receipt first.')
        return redirect(url_for('archive_list'))

    @app.post('/receipts/<identifier>/collected')
    @login_required
    def receipt_collected(identifier):
        from receipt import archive,recovery
        try:
            item=archive.load(identifier)
            if item['source']!='printed' and not recovery.read().get(identifier,{}).get('sent_at'): abort(400)
            recovery.mark(identifier,'collected_at',request.form.get('collected')=='1')
            flash('Receipt collection updated.')
        except ValueError: abort(404)
        return redirect(url_for('archive_detail',identifier=identifier))

    @app.context_processor
    def project_context():
        from receipt.recovery import status,read
        return {'receipt_delivery_status':status,'receipt_recovery_state':read}
