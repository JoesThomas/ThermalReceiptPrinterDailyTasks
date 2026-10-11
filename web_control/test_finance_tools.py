"""Explicit manual generation/printing, separate from scheduled and live previews."""

from datetime import datetime, timezone
from decimal import Decimal
from flask import abort, flash, redirect, render_template, request, session, url_for
from receipt.local_time import uk_today
from finance.test_receipt import receipt
from finance.scenario_plan import build
from finance.scenario_inputs import validate
from finance.test_forecast import is_amex


def collect(values, today):
    from finance.receipt import load_finance_settings
    from finance.projection import build_projection, money
    from finance.commitments import repayment_commitments
    from services.subscriptions import load_subscriptions

    settings = load_finance_settings().copy()
    subscriptions = load_subscriptions()
    daily = values.get("daily_spend", "").strip()
    cash = values.get("opening_cash", "").strip()
    daily_value, cash_value = money(daily), money(cash)
    if daily and (daily_value is None or not 0 <= daily_value <= 100000):
        raise ValueError("Enter a valid daily spending estimate.")
    if cash and (cash_value is None or not 0 <= cash_value <= 10000000):
        raise ValueError("Enter valid starting bank cash.")
    if daily:
        settings["runway_daily_spend"] = str(daily_value)
    if cash and daily:
        # A fully manual scenario reads local commitments without touching APIs.
        transactions = []
        balances = {
            "HSBC": {"available": cash_value},
            "MONZO": {"available": Decimal(0)},
        }
        status = {
            "monthly": subscriptions.get("monthly", [])
            + repayment_commitments(subscriptions, settings),
            "yearly": subscriptions.get("yearly", []),
        }
        coverage = "complete"
    else:
        try:
            from services import live_pipeline as pipeline
        except RuntimeError:
            raise ValueError(
                "Configure bank connections, or enter both starting cash and daily spending for a manual estimate."
            ) from None
        from services.bank_session import collect_snapshot
        snapshot = collect_snapshot(pipeline, persist=False, today=lambda: today)
        data, balances = snapshot['data'], snapshot['balances']
        transactions = data[0]
        status = pipeline.build_subscription_status(
            transactions,
            subscriptions_data=subscriptions,
            finance_settings=settings,
            today=today,
        )
        coverage = data[4].get("bank_data_status", "unavailable")
        if cash:
            balances = dict(
                balances,
                HSBC={"available": cash_value},
                MONZO={"available": Decimal(0)},
            )

    # A known card debt must have a cash cost in the scenario. With no
    # configured repayment, reserve the full balance once, conservatively today.
    def amex(item):
        return is_amex(item.get("name", ""))

    card = money(balances.get("AMEX", {}).get("current"))
    manual_card = values.get("amex_owed", "").strip()
    if manual_card:
        card = money(manual_card)
        if card is None or not 0 <= card <= 10000000:
            raise ValueError("Enter a valid non-negative Amex balance owed.")
    if card is None:
        card = next(
            (
                money(item.get("balance"))
                for item in settings.get("debts", [])
                if amex(item)
            ),
            None,
        )
    if card is not None:
        card = abs(card)
    scheduled = any(
        amex(item) and money(item.get("amount"), Decimal(0)) > 0
        for item in status["monthly"] + settings.get("commitments", [])
    ) or any(
        amex(item) and money(item.get("amount"), Decimal(0)) < 0
        for item in settings.get("forecast_events", [])
    )
    full_reserved = bool(card and not scheduled)
    if full_reserved:
        reserve_name = next(
            (
                item.get("monthly_commitment_name") or item.get("name")
                for item in settings.get("debts", [])
                if amex(item)
            ),
            "Amex balance reserve",
        )
        settings["commitments"] = list(settings.get("commitments", [])) + [
            {
                "name": reserve_name,
                "amount": str(card),
                "due_date": today.isoformat(),
                "repeat": "once",
            }
        ]
    if card is not None:
        balances = dict(balances, AMEX=dict(balances.get("AMEX", {}), current=card))
    projection = build_projection(
        balances,
        transactions,
        status["monthly"],
        status["yearly"],
        settings,
        today,
        bank_status=coverage,
    )
    if cash:
        projection["warnings"].append(
            "Starting cash is a manual scenario input, not a bank balance update."
        )
    if daily:
        projection["warnings"].append(
            "Everyday spending uses the manual daily estimate."
        )
    if cash and daily:
        projection["warnings"].append(
            "No bank lookup or payment matching was performed; local commitments are assumed outstanding."
        )
    from finance.salary_plan import reserves

    projection["reserve_details"] = reserves(settings)
    from finance.repayment_identity import unique_repayments

    projection["repayment_options"] = [
        dict(item)
        for item in unique_repayments(
            subscriptions.get("instalments", []), settings.get("debts", [])
        )
    ]
    if card is not None:
        projection["repayment_options"] = [
            item for item in projection["repayment_options"] if not amex(item)
        ]
        projection["repayment_options"].append(
            {"name": "Amex", "balance": card, "type": "credit_card"}
        )
    saved_apr = next(
        (
            money(item.get("apr", item.get("interest_rate")))
            for item in settings.get("debts", [])
            if amex(item)
        ),
        None,
    )
    if saved_apr is not None and not 0 <= saved_apr <= 100:
        saved_apr = None
    projection["amex"] = {
        "balance": card,
        "full_reserved": full_reserved,
        "scheduled": scheduled,
        "apr": saved_apr,
    }
    if full_reserved:
        projection["warnings"].append(
            "No Amex repayment schedule: full outstanding balance reserved once today. This is a conservative cash assumption, not a payment instruction."
        )
    if manual_card:
        projection["warnings"].append(
            "Amex balance is a manual scenario assumption; live debt records are unchanged."
        )
    from finance.savings_targets import load_view

    try:
        projection["savings_accounts"] = load_view(today)
    except (ValueError, OSError, TypeError, KeyError):
        if values.get("use_saved_accounts") == "on":
            raise ValueError(
                "Recorded savings could not be loaded. Check Savings goals or use a manual starting savings balance."
            ) from None
        projection["savings_accounts"] = []
        projection["warnings"].append(
            "Recorded savings accounts could not be loaded; excluded from account projections."
        )
    return projection


def payment_options():
    """Local scheduled-saving names for explicit destinations; no provider calls."""
    from finance.receipt import load_finance_settings
    from services.subscriptions import load_subscriptions
    from finance.savings_targets import is_hargreaves, payment_key

    names = {}
    for row in load_subscriptions().get("monthly", []) + load_finance_settings().get(
        "commitments", []
    ):
        name = row.get("name", "")
        if name and (row.get("category") == "savings" or is_hargreaves(name)):
            names[payment_key(name)] = name
    return [{"key": key, "name": name} for key, name in sorted(names.items())]


def register(app, login_required, start_print):
    @app.get("/finance/test")
    @login_required
    def test_finance_page():
        from receipt.archive import load

        text = None
        details = None
        identifier = session.get("test_finance_receipt")
        if identifier:
            try:
                item = load(identifier)
                candidate = item["pages"].get("finance", "")
                if candidate.startswith("-" * 42) and (
                    "SIMULATION - POTENTIAL SALARY" in candidate
                    or "SIMULATION - LUMP SUM ONLY" in candidate
                ):
                    text = candidate
                    details = item.get("test_finance")
            except ValueError:
                pass
        from finance.receipt import load_finance_settings
        from finance.savings_targets import load_view

        try:
            saved_savings = load_view(uk_today())
        except (ValueError, OSError, TypeError, KeyError):
            saved_savings = []
        defaults = {
            "use_saved_accounts": "on"
            if session.get("test_finance_use_accounts", bool(saved_savings))
            else "",
            "savings_target": str(
                load_finance_settings().get("salary_savings_target") or 0
            ),
            "save_all": "on" if session.get("test_finance_save_all", True) else "",
            "invest_spare_cash": "on"
            if session.get("test_finance_invest_spare_cash", True)
            else "",
            "equal_savings": "on"
            if session.get("test_finance_equal_savings", True)
            else "",
            "strategy": session.get("test_finance_strategy", "amex_first"),
        }
        if isinstance(details, dict) and isinstance(details.get("values"), dict):
            defaults.update(
                {
                    key: value
                    for key, value in details["values"].items()
                    if isinstance(value, str)
                }
            )
        return render_template(
            "test_finance.html",
            today=uk_today(),
            result_text=text,
            values=defaults,
            saved_savings=saved_savings,
            payment_options=payment_options(),
            scenario_details=details,
        )

    @app.post("/finance/test/generate")
    @login_required
    def generate_test_finance():
        today = uk_today()
        values = request.form.to_dict()
        values.setdefault("save_all", "")
        values.setdefault("invest_spare_cash", "")
        values.setdefault("equal_savings", "")
        values.setdefault("use_saved_accounts", "")
        try:
            validate(values, today)
            projection = collect(values, today)
            result = build(projection, values, today)
            from finance.test_scenarios import compare

            details = compare(projection, values, today, current=result)
            details["values"] = {
                key: value for key, value in values.items() if key != "csrf_token"
            }
            result["sensitivity"] = details["sensitivity"]
            result["contribution"] = details["contribution"]
            text = receipt(result, today)
            from receipt.archive import save

            identifier = save(
                {"finance": text},
                {},
                datetime.now(timezone.utc).isoformat(),
                "preview",
                {},
                test_finance=details,
            )
            session["test_finance_receipt"] = identifier
            session["test_finance_equal_savings"] = values["equal_savings"] == "on"
            session["test_finance_invest_spare_cash"] = (
                values["invest_spare_cash"] == "on"
            )
            session["test_finance_use_accounts"] = values["use_saved_accounts"] == "on"
            session["test_finance_strategy"] = values.get("strategy", "savings_first")
            if values.get("mode", "replace") != "lump":
                session["test_finance_save_all"] = values["save_all"] == "on"
            flash(
                "Test receipt generated privately. Nothing has been sent to the printer."
            )
            return redirect(url_for("test_finance_page"))
        except (ValueError, OSError, TypeError) as error:
            # Validation messages are local; provider failures are handled in collect.
            return render_template(
                "test_finance.html",
                today=today,
                result_text=None,
                values=values,
                saved_savings=[],
                payment_options=payment_options(),
                error=str(error),
            ), 400

    @app.post("/finance/test/print")
    @login_required
    def print_test_finance():
        from receipt.archive import load

        identifier = session.get("test_finance_receipt")
        if not identifier:
            abort(400)
        try:
            item = load(identifier)
        except ValueError:
            abort(404)
        if not any(
            label in item["pages"].get("finance", "")
            for label in ("SIMULATION - POTENTIAL SALARY", "SIMULATION - LUMP SUM ONLY")
        ):
            abort(400)
        started, error = start_print(["--archive", identifier, "finance"])
        flash("Test finance receipt queued." if started else error)
        return redirect(url_for("test_finance_page"))
