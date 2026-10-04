"""Mobile daily actions and local printer/source diagnostics."""
import os
from datetime import datetime, timezone
from pathlib import Path
from flask import flash, redirect, render_template, url_for
from receipt.printer import DEFAULT_NETWORK_HOST, DEFAULT_NETWORK_PORT, readiness
from receipt.local_time import uk_receipt_time
from storage import write_json
from web_control.today_summary import dashboard, read
from services.source_cache import timings, refresh


def register(app, login_required, root, start_print, recipes_fn, meal_confirmation):
    diagnostic = root / 'data' / 'printer_diagnostics.json'

    @app.get('/quick-actions')
    @login_required
    def quick_actions():
        try: _, recipes = recipes_fn()
        except (OSError,ValueError,RuntimeError): recipes = []
        from actions.checklists import today
        from datetime import date
        return render_template('quick_actions.html',today_view=dashboard(),recipes=recipes,
                               confirmed=meal_confirmation(date.fromisoformat(today())))

    @app.get('/printer-diagnostics')
    @login_required
    def printer_diagnostics():
        state = read(diagnostic)
        rows = [dict(row, checked=uk_receipt_time(row.get('source_checked_at')),
                     attempted=uk_receipt_time(row.get('attempted_at'))) for row in timings()]
        return render_template('printer_diagnostics.html',connection=os.getenv('RECEIPT_PRINTER_CONNECTION','network'),
                               host=os.getenv('RECEIPT_PRINTER_HOST',DEFAULT_NETWORK_HOST),
                               port=os.getenv('RECEIPT_PRINTER_PORT',str(DEFAULT_NETWORK_PORT)),
                               state=state,checked=uk_receipt_time(state.get('checked_at')),timings=rows)

    @app.post('/printer-diagnostics/check')
    @login_required
    def printer_check():
        available,message = readiness()
        try: write_json(diagnostic, {'reachable':available,'message':message,'checked_at':datetime.now(timezone.utc).isoformat()})
        except OSError: flash('Connection checked, but diagnostic history could not be saved.')
        flash(message)
        return redirect(url_for('printer_diagnostics'))

    @app.post('/printer-diagnostics/test')
    @login_required
    def printer_test():
        ok,error = start_print(['--printer-test'])
        flash('Short test receipt queued.' if ok else error)
        return redirect(url_for('printer_diagnostics'))

    @app.post('/sources/refresh')
    @login_required
    def source_refresh():
        try:
            refresh()
            flash('The next receipt will try fresh calendar and delivery data; cached fallback stays available.')
        except OSError: flash('Source refresh preference could not be saved.')
        return redirect(url_for('printer_diagnostics'))
