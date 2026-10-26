"""Owner-confirmed settlement and reversible reopening of saved instalments."""

from flask import flash, redirect, request, url_for
from finance import instalment_settlement as settlement
from finance.subscription_store import store
from receipt.local_time import uk_today


def register(app, login_required, file_path):
    @app.context_processor
    def context():
        return dict(
            instalment_settlement_key=settlement.identity,
            instalment_settlement_links=settlement.linked_monthly,
            settlement_today=uk_today(),
        )

    @app.post("/instalment/<int:index>/settle")
    @login_required
    def instalment_settle(index):
        try:

            def update(value):
                settlement.settle(
                    value,
                    index,
                    request.form.get("key", ""),
                    request.form.get("date", ""),
                    uk_today(),
                    monthly_key=request.form.get("monthly_key")
                    if request.form.get("also_monthly") == "on"
                    else None,
                )

            store(file_path()).update(update)
            flash(
                "Instalment marked settled. Regenerate Finance and test receipts. No payment was sent or Direct Debit cancelled."
            )
        except (ValueError, OSError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Settlement could not be saved."
            )
        return redirect(url_for("index", view="accounts") + "#instalments")

    @app.post("/instalment/<int:index>/reopen")
    @login_required
    def instalment_reopen(index):
        try:
            store(file_path()).update(
                lambda value: settlement.reopen(
                    value, index, request.form.get("key", "")
                )
            )
            flash(
                "Instalment reopened with its previous recorded balance and schedule. No bank records were changed."
            )
        except (ValueError, OSError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Settlement could not be reopened."
            )
        return redirect(url_for("index", view="accounts") + "#instalments")
