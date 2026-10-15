"""Finance review calculations and routes, independent of the main web module."""

from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import flash, jsonify, redirect, render_template, request, url_for
from receipt_settings import load_receipt_settings
from web_control.finance_refresh import FinanceRefresh


def build_review(deps, snapshot, fresh, refresh_status=None):
    app = deps.app
    PROJECT_ROOT = deps.root
    _wealth_view = deps.wealth_view
    finance_charts = deps.finance_charts
    external_payments = deps.external_payments
    monthly_payments = deps.monthly_payments
    incoming_review = deps.incoming_review
    cash_flow_review = deps.cash_flow_review
    from finance.premium_bonds import review as review_bond_prizes
    from finance.commitments import matching_repayment_transaction
    from finance.yearly_subscriptions import annual_subscription_rows
    from services.live_pipeline import (
        build_subscription_status,
        analyse_incoming_payments,
        matching_subscription_transaction,
    )

    today = datetime.now(ZoneInfo("Europe/London")).date()
    try:
        bonds_summary = review_bond_prizes(today)
    except (ValueError, OSError):
        bonds_summary = None
    try:
        wealth, wealth_error = _wealth_view(), None
    except (ValueError, OSError, KeyError, TypeError):
        wealth, wealth_error = None, "Private balance history could not be loaded."
    try:
        finance_data = list(snapshot["data"])
        finance_data[4] = dict(finance_data[4])
        if not fresh:
            finance_data[4]["bank_data_status"] = "partial"
        transactions = finance_data[0]
        try:
            bonds_summary = review_bond_prizes(today)
        except (ValueError, OSError):
            bonds_summary = None
        bank_data_status = finance_data[4].get("bank_data_status", "unavailable")
        status = build_subscription_status(transactions, today=today)
        annual = annual_subscription_rows(status["yearly"], transactions, today)
        used = set()
        rows = []
        for item in status["monthly"]:
            index = matching_subscription_transaction(item, transactions, today, used)
            method = "Merchant and amount"
            if index is None and item.get("category") == "repayment":
                index = matching_repayment_transaction(item, transactions, today, used)
                method = "Payment date and amount"
            if index is not None:
                used.add(index)
            tx = transactions[index] if index is not None else None
            rows.append({"item": item, "transaction": tx, "method": method})
        from web_control.reconciliation import review_queue as build_queue

        has_uncertain_payments = False
        reviewable_payment_ids = set()
        try:
            review_queue = (
                build_queue(transactions, rows, today)
                if fresh
                else {"payments": [], "unmatched": [], "reviewable": []}
            )
            has_uncertain_payments = bool(
                review_queue["payments"] or review_queue["unmatched"]
            )
            reviewable_payment_ids = {
                row["id"] for row in review_queue.get("reviewable", [])
            }
        except (OSError, ValueError):
            app.logger.warning("Finance review queue could not be saved.")
        payments = external_payments(transactions)
        charts = finance_charts(payments, status["monthly"], today)
        month = monthly_payments(transactions, today)
        salary, other = analyse_incoming_payments(
            transactions,
            salary_payee=load_receipt_settings()
            .get("finance", {})
            .get("salary_payee", ""),
        )
        income = incoming_review(salary, other, today)
        cash_flow = cash_flow_review(income, payments, today)
        from finance.projection import build_projection
        from finance.receipt import load_finance_settings
        from savings_runway import load_savings, savings_totals
        from web_control.finance_suggestions import build_suggestions

        forecast_settings = load_finance_settings()
        try:
            balances = snapshot["balances"]
        except Exception:
            app.logger.warning("Cash balances unavailable for finance projection")
            balances = {}
        from finance.wealth_history import apply_latest

        savings_data = load_savings(PROJECT_ROOT / "data" / "savings.json")
        if wealth:
            savings_data, _ = apply_latest(savings_data, {"accounts": []}, wealth)
        savings = savings_totals(savings_data)["runway_accessible"]
        projection = build_projection(
            balances,
            transactions,
            status["monthly"],
            status["yearly"],
            forecast_settings,
            today,
            savings,
            bank_data_status,
        )
        suggestions = build_suggestions(
            projection,
            rows,
            annual,
            status["ended"],
            charts,
            finance_data[3],
            transactions,
            today,
        )
        from web_control.finance_insights import build as build_insights
        from finance.savings_goals import review as goals_review

        try:
            goals_view = goals_review(wealth, on=today)
        except (ValueError, OSError, KeyError, TypeError):
            goals_view = None
        insights = build_insights(
            projection,
            balances,
            finance_data[4],
            month,
            income,
            wealth,
            goals_view,
            today,
        )
        from finance.salary_plan import build as build_salary_plan
        from finance import planning as private_planning

        try:
            plans = private_planning.load()
        except (ValueError, TypeError, OSError):
            plans = None
        salary_plan = build_salary_plan(
            salary,
            transactions,
            balances,
            projection,
            forecast_settings,
            goals_view,
            today,
        )
        try:
            if plans is None:
                raise ValueError("Planning data unavailable")
            planning_view = {
                "state": plans,
                "scenario": private_planning.scenario(
                    projection, plans.get("purchases", []), today
                ),
                "allocation": private_planning.allocation(
                    salary_plan,
                    plans.get("priorities", []),
                    goals_view,
                    plans.get("purchases", []),
                    today,
                ),
                "reminders": private_planning.reminders(
                    projection,
                    status["monthly"],
                    status["yearly"],
                    forecast_settings,
                    today,
                ),
            }
        except (ValueError, TypeError, OSError, KeyError):
            planning_view = {
                "error": "Private plans could not be read. Restore a valid backup."
            }
        from finance.assets import net_worth as build_net_worth
        from finance.receipt import calculate_debt_and_payday

        debt_view = calculate_debt_and_payday(
            projection["cash"] or 0,
            balances.get("AMEX", {}).get("current") or 0,
            finance_data[3],
            forecast_settings,
            today,
        )
        net_worth = build_net_worth(
            projection["cash"],
            savings_totals(savings_data)["total"],
            (wealth or {}).get("investments"),
            debt_view["debts"],
            forecast_settings,
            today,
        )
        if plans and plans.get("cashflow"):
            from finance.cash_scenarios import build as build_cash_scenario

            try:
                planning_view["cashflow_result"] = build_cash_scenario(
                    projection, plans["cashflow"], today
                )
            except ValueError as error:
                planning_view["cashflow_result"] = {
                    "valid": False,
                    "reason": str(error),
                }
        net_worth["complete"] = (
            net_worth["complete"]
            and bank_data_status == "complete"
            and balances.get("AMEX", {}).get("current") is not None
        )
        from finance import reviews as finance_reviews
        from finance.rental_tax import (
            estimate as rental_estimate,
            load as load_rental_plan,
        )

        rental_plan = rental_estimate(load_rental_plan(), today)
        update_items = finance_reviews.needs_update(
            projection, net_worth, bank_data_status, forecast_settings, rental_plan
        )
        from finance.credit_limits import summary as credit_summary
        from receipt.lifestyle import load as lifestyle_settings

        credit_cards = credit_summary(
            lifestyle_settings().get("credit_cards", []), balances
        )
        return dict(
            observation=dict(transactions=transactions, summary=finance_data[4], rental_plan=rental_plan),
            update_items=update_items,
            net_worth=net_worth,
            credit_cards=credit_cards,
            planning_view=planning_view,
            insights=insights,
            salary_plan=salary_plan,
            has_uncertain_payments=has_uncertain_payments,
            reviewable_payment_ids=reviewable_payment_ids,
            rows=rows,
            charts=charts,
            wealth=wealth,
            wealth_error=wealth_error,
            bonds_summary=bonds_summary,
            month=month,
            income=income,
            cash_flow=cash_flow,
            annual=annual,
            projection=projection,
            suggestions=suggestions,
            forecast_settings=forecast_settings,
            ended_contracts=status["ended"],
            bank_data_status=bank_data_status,
            checked_at=today,
            checked_time=datetime.fromisoformat(snapshot["checked_at"])
            .astimezone(ZoneInfo("Europe/London"))
            .strftime("%d %b %Y, %H:%M %Z"),
            snapshot=snapshot,
            snapshot_fresh=fresh,
            refresh_status=refresh_status,
            accessible_savings=savings,
            error=None,
        )
    except Exception:
        app.logger.exception("Could not load finance review")
        return dict(
            http_status=503,
            rows=[],
            checked_at=today,
            wealth=wealth,
            wealth_error=wealth_error,
            bonds_summary=bonds_summary,
            error="Bank transactions are unavailable. Try again later.",
            snapshot=snapshot,
            snapshot_fresh=False,
            refresh_status=refresh_status,
        )


def render_review(deps, snapshot, fresh, refresh_status):
    model = build_review(deps, snapshot, fresh, refresh_status)
    from finance.expected_income import view as expected_income_view
    from receipt.local_time import uk_today
    model['expected_income'] = expected_income_view(model.get('projection'), uk_today())
    return render_template('finance_review.html', **model), model.get('http_status', 200)


def capture_review(deps, snapshot):
    "Only successful refreshes record observations; displaying a page never does."
    from copy import copy
    from finance.wealth_history import capture_local, review
    from finance.investments import load_investments
    from savings_runway import load_savings
    from web_control.finance_insights import snapshots
    from web_control.reconciliation import save_review
    from finance.reviews import capture
    today = datetime.fromisoformat(snapshot['checked_at']).astimezone(ZoneInfo('Europe/London')).date()
    capture_local(load_savings(deps.root/'data'/'savings.json'), load_investments(deps.root/'data'/'investments.json'), today)
    readonly = copy(deps)
    readonly.wealth_view = lambda: review(today)
    model = build_review(readonly, snapshot, True)
    if model.get('http_status'):
        raise ValueError('Finance observation could not be calculated')
    observation = model['observation']
    snapshots(model['insights']['observation'])
    save_review(observation['transactions'], model['rows'], today)
    capture(model['salary_plan'], observation['transactions'], model['rows'], model['income'],
            model['projection'], observation['summary'], model['net_worth'], observation['rental_plan'],
            today, model['month']['total'])


def register(app, login_required, deps):
    refresh = FinanceRefresh(deps.root, on_success=lambda snapshot:capture_review(deps,snapshot))
    app.extensions["finance_refresh"] = refresh
    _local_today = deps.today

    @app.get("/finance-review")
    @login_required
    def finance_review():
        snapshot = refresh.read()
        fresh = refresh.fresh(snapshot)
        if not fresh:
            refresh.start()
        status = refresh.status()
        if snapshot:
            try:
                return render_review(deps, snapshot, fresh, status)
            except (RuntimeError, OSError, ValueError):
                status = {
                    "state": "failed",
                    "stage": "Finance configuration unavailable. Check settings and try again.",
                }
        from finance.expected_income import view as expected_income_view
        return render_template("finance_loading.html", refresh_status=status,
                               expected_income=expected_income_view(None, _local_today()))

    @app.post("/finance-review/refresh")
    @login_required
    def refresh_finance():
        refresh.start(force=True)
        if request.headers.get("Accept") == "application/json":
            return jsonify(refresh.public_status()), 202
        return redirect(url_for("finance_review"))

    @app.get("/finance-review/status")
    @login_required
    def finance_refresh_status():
        return jsonify(refresh.public_status())

    @app.post("/finance-review/dismiss")
    @login_required
    def dismiss_finance_suggestion():
        from web_control.finance_suggestions import dismiss_suggestion

        try:
            dismiss_suggestion(request.form.get("suggestion_id", ""), _local_today())
        except ValueError:
            return ("Invalid suggestion", 400)
        return redirect(url_for("finance_review") + "#finance-suggestions")

    @app.post("/finance-review/salary-settings")
    @login_required
    def salary_settings():
        from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings
        from finance.projection import money
        from storage import write_json

        try:
            settings = load_finance_settings()
            for field in (
                "hsbc_emergency_reserve",
                "physical_cash_target",
                "physical_cash_held",
                "salary_savings_target",
            ):
                raw = request.form.get(field, "").strip()
                value = money(raw) if raw else None
                if raw and (value is None or value < 0):
                    raise ValueError("Use non-negative amounts.")
                settings[field] = float(value) if value is not None else None
            recorded = request.form.get("physical_cash_date", "").strip()
            on = date.fromisoformat(recorded) if recorded else None
            if settings["physical_cash_held"] is not None and (
                not on or on > _local_today()
            ):
                raise ValueError("Record a cash count date no later than today.")
            settings["physical_cash_date"] = on.isoformat() if on else None
            write_json(FINANCE_SETTINGS_FILE, settings)
            flash("Salary targets and emergency reserves saved privately.")
        except (ValueError, TypeError, OSError):
            flash("Use valid amounts and a cash count date no later than today.")
        return redirect(
            url_for(
                "savings_review"
                if request.form.get("return_to") == "savings"
                else "finance_review"
            )
        )

    @app.post("/finance-review/forecast-settings")
    @login_required
    def save_forecast_settings():
        from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings
        from finance.projection import money

        try:
            settings = load_finance_settings()
            payday = request.form.get("next_payday", "").strip()
            settings["next_payday"] = (
                date.fromisoformat(payday).isoformat() if payday else None
            )
            repeat = request.form.get("payday_repeat", "once")
            if repeat not in {"once", "monthly"}:
                raise ValueError("Invalid payday repeat")
            settings["payday_repeat"] = repeat
            buffer = money(request.form.get("emergency_buffer", "0"))
            daily_text = request.form.get("runway_daily_spend", "").strip()
            daily = money(daily_text) if daily_text else None
            if (
                buffer is None
                or buffer < 0
                or (daily_text and (daily is None or daily < 0))
            ):
                raise ValueError("Enter non-negative amounts")
            settings["emergency_buffer"] = float(buffer)
            settings["runway_daily_spend"] = float(daily) if daily is not None else None
            from storage import write_json

            write_json(FINANCE_SETTINGS_FILE, settings)
            flash("Projection settings saved locally.")
        except (ValueError, OverflowError):
            flash("Enter a valid payday and non-negative amounts.")
        return redirect(url_for("finance_review") + "#finance-forecast")

    @app.post("/finance-review/payment/add")
    @login_required
    def add_forecast_payment():
        from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings
        from finance.projection import money

        try:
            name = request.form.get("name", "").strip()
            amount = money(request.form.get("amount"))
            due = date.fromisoformat(request.form.get("due_date", "")).isoformat()
            repeat = request.form.get("repeat", "once")
            if (
                not name
                or len(name) > 90
                or amount is None
                or amount <= 0
                or repeat not in {"once", "monthly", "yearly"}
            ):
                raise ValueError("Invalid payment")
            settings = load_finance_settings()
            items = settings.setdefault("commitments", [])
            if len(items) >= 100:
                raise ValueError("Too many payments")
            items.append(
                {
                    "name": name,
                    "amount": float(amount),
                    "due_date": due,
                    "repeat": repeat,
                }
            )
            from storage import write_json

            write_json(FINANCE_SETTINGS_FILE, settings)
            flash("Dated payment saved locally.")
        except (ValueError, OverflowError):
            flash("Enter a valid payment name, amount and date.")
        return redirect(url_for("finance_review") + "#finance-forecast")

    @app.post("/finance-review/payment/<int:index>/delete")
    @login_required
    def delete_forecast_payment(index):
        from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings

        settings = load_finance_settings()
        items = settings.get("commitments", [])
        if index >= len(items):
            return ("Payment not found", 404)
        items.pop(index)
        from storage import write_json

        write_json(FINANCE_SETTINGS_FILE, settings)
        return redirect(url_for("finance_review") + "#finance-forecast")
