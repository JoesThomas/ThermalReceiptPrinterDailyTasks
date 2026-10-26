"""Editable balance thresholds reuse the local Amex evidence and existing polling."""

from flask import flash, redirect, request, session, url_for
from finance import amex_balance as alerts
from finance.amex_protection import store, validate


def register(app, login_required):
    @app.context_processor
    def context():
        return (
            {"amex_balance_alert": alerts.view()}
            if session.get("authenticated")
            else {}
        )

    @app.post("/finance/amex-balance/settings")
    @login_required
    def save_amex_balance_settings():
        try:

            def update(value):
                value["balance_alert_enabled"] = request.form.get("enabled") == "on"
                value["balance_alert_threshold"] = request.form.get(
                    "threshold", ""
                ).strip()
                validate(value)

            store().update(update)
            flash(
                "Amex balance alerts saved. This does not change repayments or interest warnings."
            )
        except (ValueError, OSError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Balance alert settings could not be saved."
            )
        return redirect(url_for("finance_review") + "#amex-balance-settings")
