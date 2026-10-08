"""Read-only print planning and explicitly requested saved-copy printing."""
from flask import abort, flash, redirect, render_template, request, url_for
from receipt.capture import LIVE_PREVIEW_FILE, load_capture

RETRIES = {'Weather':'information', 'UK news':'information', 'Local news':'information',
           'Sport news':'information', 'Calendar':'actions', 'Deliveries':'actions', 'Google Docs':'actions'}


def register(app, login_required, start_print, root):
    @app.context_processor
    def receipt_control_context():
        return {'receipt_retries': RETRIES}

    @app.get('/print-plan')
    @login_required
    def print_plan():
        from receipt_settings import load_receipt_settings
        from web_control.today_summary import dashboard
        from web_control.printer_setup import installation_checks
        settings = load_receipt_settings()
        from meals import legacy_planner as meals
        from receipt.local_time import uk_today
        try:
            meal_plan=meals.load_plan_for(uk_today())
            meal=next((row for row in (meal_plan or {}).get('meals',[]) if row.get('date')==uk_today().isoformat()), {})
            meal_name=meal.get('recipe',{}).get('name') or meal.get('name') or 'No saved meal plan yet'
        except (ValueError,OSError,KeyError): meal_name='Meal plan unavailable'
        return render_template('print_plan.html', settings=settings, today_view=dashboard(), meal_name=meal_name,
                               installation=installation_checks(root))

    @app.post('/print-plan')
    @login_required
    def print_plan_start():
        from receipt.selection import validate
        try: pages = validate(request.form.getlist('pages'))
        except ValueError: abort(400)
        started, error = start_print(['--pages', *pages])
        flash('Selected receipt pages queued.' if started else error)
        return redirect(url_for('preview'))

    @app.post('/preview/print-saved')
    @login_required
    def print_saved_preview():
        if request.form.get('confirm_saved') != 'on':
            flash('Confirm you want to print the saved copy, with its original data.')
            return redirect(url_for('preview'))
        capture = load_capture(LIVE_PREVIEW_FILE)
        if not capture or not capture['pages']: abort(404)
        page = request.form.get('page', 'all')
        names = [name for name in capture.get('page_order', []) if name in capture['pages']] if page == 'all' else [page]
        if request.form.getlist('pages'):
            from receipt.selection import validate
            try: requested=validate(request.form.getlist('pages'))
            except ValueError: abort(400)
            names=[name for name in names if name in requested]
            if len(names) != len(requested): abort(400)
        if not names or any(name not in capture['pages'] for name in names): abort(400)
        from receipt.repeat_guard import recent, record
        import hashlib, json
        stable_args=['--saved-preview',hashlib.sha256(json.dumps(capture,sort_keys=True).encode()).hexdigest(),','.join(names)]
        if recent(root,stable_args) and request.form.get('allow_repeat') != 'on':
            flash('This saved copy was just queued. Allow intentional reprint to send it again.')
            return redirect(url_for('preview'))
        from receipt.archive import save
        # Freeze a server-owned snapshot before queuing; subsequent previews cannot change this print.
        captured_at = min(capture['page_times'].get(name, '') for name in names)
        identifier = save({name:capture['pages'][name] for name in names},
                          {name:capture.get('page_images', {}).get(name, []) for name in names},
                          captured_at, 'preview', capture.get('freshness', {}))
        started, error = start_print(['--archive', identifier, 'all'])
        if started: record(root,stable_args)
        flash('Saved copy queued. Data was not refreshed.' if started else error)
        return redirect(url_for('preview'))
