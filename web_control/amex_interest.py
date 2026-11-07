"""Authenticated local interest alerts; polling does not trigger bank requests."""
from flask import flash, jsonify, redirect, request, url_for
from finance import amex_interest as interest
from web_control.amex_alert_scope import balance_for, scope


def register(app, login_required):
    def interest_state():
        try:
            return {'charges': interest.pending(), 'error': None}
        except (ValueError, OSError):
            return {'charges': [], 'error': 'Amex interest alerts could not be read. Check private data.'}

    @app.context_processor
    def alert_context():
        return {'amex_interest_alert': interest_state()} if scope() == "finance" else {}

    @app.get('/finance/amex-interest/status')
    @login_required
    def amex_interest_status():
        page = "home" if request.args.get("home") == "1" else "finance"
        balance = balance_for(page)
        result = {
            "balance": {key: balance[key] for key in (
                "show", "level", "title", "message", "amount_text",
                "threshold_text", "checked", "stale",
            )}
        }
        if page == "finance":
            from web_control.amex_protection import view
            result.update(interest_state(), protection=view()["warnings"])
        return jsonify(result)

    @app.post('/finance/amex-interest/acknowledge')
    @login_required
    def acknowledge_amex_interest():
        try:
            interest.acknowledge(request.form.getlist('charge_id'))
            flash('Amex interest warning acknowledged. This does not change the card balance or cancel the charge.')
        except (ValueError, OSError):
            flash('Amex interest warning could not be acknowledged. Check private data.')
        return redirect(url_for('finance_review'))
