"""Authenticated local interest alerts; polling does not trigger bank requests."""
from flask import flash, jsonify, redirect, request, session, url_for
from finance import amex_interest as interest


def register(app, login_required):
    def state():
        try:
            return {'charges': interest.pending(), 'error': None}
        except (ValueError, OSError):
            return {'charges': [], 'error': 'Amex interest alerts could not be read. Check private data.'}

    @app.context_processor
    def alert_context():
        return {'amex_interest_alert': state() if session.get('authenticated') else {'charges': [], 'error': None}}

    @app.get('/finance/amex-interest/status')
    @login_required
    def amex_interest_status():
        return jsonify(state())

    @app.post('/finance/amex-interest/acknowledge')
    @login_required
    def acknowledge_amex_interest():
        try:
            interest.acknowledge(request.form.getlist('charge_id'))
            flash('Amex interest warning acknowledged. This does not change the card balance or cancel the charge.')
        except (ValueError, OSError):
            flash('Amex interest warning could not be acknowledged. Check private data.')
        return redirect(url_for('finance_review'))
