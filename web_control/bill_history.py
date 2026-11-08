from flask import flash, redirect, render_template, request, url_for

from finance import bill_history
from services import subscriptions


def register(app, login_required):
    @app.context_processor
    def bill_history_context():
        return {"bill_history_available": True}

    @app.route("/finance/bill-history", endpoint="bill_history", methods=["GET", "POST"])
    @login_required
    def bill_history_page():
        if request.method == "POST":
            try:
                bill_history.decide(subscriptions.SUBSCRIPTIONS_FILE, request.form.get("key"),
                                    request.form.get("decision"))
                flash("Bill decision saved. The actual payment is unchanged.")
            except ValueError as error:
                flash(str(error))
            except OSError:
                flash("Could not save the bill decision.")
            return redirect(url_for("bill_history"))
        try:
            rows = bill_history.entries(subscriptions.load_subscriptions())
        except (OSError, ValueError, KeyError, TypeError):
            rows = []
            flash("Saved bill history could not be read.")
        return render_template("bill_history.html", rows=rows)
