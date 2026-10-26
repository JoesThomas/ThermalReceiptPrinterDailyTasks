"""Authenticated, local-only long-term planning; no provider or document access."""

from datetime import datetime, timezone
import hashlib
from flask import abort, flash, redirect, render_template, request, session, url_for
from receipt.local_time import uk_today
from finance.long_range.config import (
    defaults,
    account,
    validate,
    KINDS,
    EVENTS,
    NUMBERS,
)
from finance.long_range import store as records
from finance.long_range.report import compare, receipt
from finance.money import format_pounds


def form_config(form, today):
    config = defaults(today)
    for key in (
        "name",
        "start",
        "reviewed",
        "years",
        "inflation",
        "salary",
        "other_income",
        "bills",
        "spending",
        "debt_spending",
        "income_growth",
        "spending_growth",
        "minimum",
        "isa_allowance",
        "cash_isa_limit",
    ):
        config[key] = form.get(key, config[key])
    for key in ("isa_enabled", "invest_without_salary"):
        config[key] = form.get(key) == "on"
    config["accounts"] = []
    ids = form.getlist("a_id")
    if len(ids) > 40:
        raise ValueError("Use at most 40 accounts.")
    for i, key in enumerate(ids):

        def get(field, default=""):
            values = form.getlist("a_" + field)
            return values[i] if i < len(values) else default

        row = account(id=key, name=get("name"), kind=get("kind"))
        for field in NUMBERS:
            row[field] = get(field, NUMBERS[field])
        for field in ("unlock", "payout"):
            row[field] = get(field, row[field])
        for field in ("stop", "early", "scheduled", "extra"):
            row[field] = get(field) == "yes"
        config["accounts"].append(row)
    for prefix, collection, fields in [
        ("e", "events", ("name", "date", "kind", "amount", "account", "repeat")),
        ("g", "goals", ("name", "date", "amount", "account", "inflates")),
    ]:
        config[collection] = []
        for i, name in enumerate(form.getlist(prefix + "_name")):
            row = {field: form.getlist(prefix + "_" + field)[i] for field in fields}
            if prefix == "g":
                row["inflates"] = row["inflates"] == "yes"
            config[collection].append(row)
    return config


def import_local(config, today):
    from finance.savings_targets import load_view

    known = {a["name"].casefold() for a in config["accounts"]}
    for row in load_view(today):
        name = row.get("label", row["name"])
        if row["balance"] is None or name.casefold() in known:
            continue
        kind = (
            row["type"]
            if row["type"] in KINDS
            else "investment"
            if row["kind"] == "investment"
            else "savings"
        )
        if name.casefold() in ("cash", "physical cash"):
            kind = "cash"
        rate = (
            str(row.get("interest_rate") or 0)
            if kind in ("savings", "cash_isa")
            else "0"
        )
        config["accounts"].append(
            account(
                name,
                kind,
                id=hashlib.sha256(row["id"].encode()).hexdigest()[:12],
                balance=str(row["balance"]),
                target=str(row.get("target") or 0),
                limit=str(row.get("balance_limit") or ""),
                low=rate,
                expected=rate,
                high=rate,
                isa_used=str(row.get("isa_contributions") or 0),
                stop=kind == "cash",
            )
        )
        known.add(name.casefold())
    # Property ownership and mortgage balances are deliberately entered separately;
    # do not infer ownership, pension access dates, income or live bank cash.
    return config


def register(app, login_required, start_print):
    @app.context_processor
    def planning_context():
        return {"long_term_available": True}

    @app.get("/finance/long-term")
    @login_required
    def long_term_page():
        state = records.store().read()
        row = state["plans"].get(request.args.get("plan", ""))
        if request.args.get("plan") and row is None:
            abort(404)
        config = row["config"] if row else defaults(uk_today())
        report = compare(config, state["observations"]) if row else None
        return render(config, report, state)

    def render(config, report=None, state=None, error=None, status=200):
        state = state or records.store().read()
        text = receipt(config, report) if report else None
        try:
            inspection_year = max(
                1,
                min(
                    int(config["years"]),
                    int(request.values.get("inspection_year", "1")),
                ),
            )
        except ValueError:
            inspection_year = 1
        display_points = (
            report["expected"]["points"][
                (inspection_year - 1) * 12 : (
                    len(report["expected"]["points"])
                    if inspection_year == int(config["years"])
                    else inspection_year * 12
                )
            ]
            if report
            else []
        )
        return render_template(
            "long_term.html",
            config=config,
            report=report,
            result_text=text,
            plans=state["plans"],
            observations=state["observations"],
            inspection_year=inspection_year,
            display_points=display_points,
            kinds=KINDS,
            event_kinds=EVENTS,
            account_template=account(),
            today=uk_today(),
            money=format_pounds,
            error=error,
        ), status

    @app.post("/finance/long-term")
    @login_required
    def long_term_generate():
        config = defaults(uk_today())
        try:
            config = form_config(request.form, uk_today())
            action = request.form.get("action", "forecast")
            if action == "import":
                config = import_local(config, uk_today())
                validate(config)
                flash(
                    "Local recorded savings copied into this form. Review balances, bank cash, debts, access dates and assumptions; nothing live was changed."
                )
                return render(config)
            if action == "rebase":
                state = records.store().read()
                latest = {}
                for observed in sorted(state["observations"], key=lambda r: r["date"]):
                    latest[observed["account"]] = observed
                for a in config["accounts"]:
                    if a["id"] in latest:
                        a["balance"] = latest[a["id"]]["balance"]
                today = uk_today()
                config["start"] = today.isoformat()
                config["reviewed"] = today.isoformat()
                future = []
                from finance.projection import occurs

                for e in sorted(config["events"], key=lambda e: e["date"]):
                    if e["date"] >= today.isoformat():
                        future.append(e)
                        continue
                    if e["kind"] in ("salary", "other_income", "bills", "spending"):
                        config[e["kind"]] = e["amount"]
                    if e["kind"] == "contribution":
                        for a in config["accounts"]:
                            if a["id"] == e["account"]:
                                a["monthly"] = e["amount"]
                    if int(e["repeat"]):
                        on = datetime.fromisoformat(e["date"]).date()
                        while on < today:
                            on = occurs(on, int(e["repeat"]))
                        e = dict(e, date=on.isoformat())
                        future.append(e)
                config["events"] = future
                config["goals"] = [
                    g for g in config["goals"] if g["date"] >= today.isoformat()
                ]
                validate(config)
                flash(
                    "New form starts today using latest recorded balances where available. Unobserved accounts keep entered balances; review their dates. Past one-off events and elapsed goals were removed; the old saved baseline is unchanged."
                )
                return render(config)
            config = validate(config)
            if action == "save":
                key = records.save(config)
                flash(
                    "Saved an immutable planning baseline. Future edits create a new version."
                )
                return redirect(url_for("long_term_page", plan=key))
            report = compare(config, records.store().read()["observations"])
            if action == "receipt":
                from receipt.archive import save

                key = save(
                    {"finance": receipt(config, report)},
                    {},
                    datetime.now(timezone.utc).isoformat(),
                    "preview",
                    {},
                )
                session["long_term_receipt"] = key
                flash("Long-term summary archived privately; no paper printed.")
            return render(config, report)
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            OverflowError,
            OSError,
        ) as error:
            return render(config, error=str(error), status=400)

    @app.post("/finance/long-term/observe")
    @login_required
    def long_term_observe():
        try:
            records.observe(
                request.form["account"],
                request.form["date"],
                request.form["balance"],
                request.form.get("note", ""),
                uk_today(),
            )
            flash(
                "Actual valuation saved privately. Exact month-end dates can be compared with a saved baseline."
            )
        except (ValueError, KeyError, OSError) as error:
            flash(str(error))
        return redirect(url_for("long_term_page", plan=request.form.get("plan", "")))

    @app.post("/finance/long-term/observe/delete")
    @login_required
    def long_term_observation_delete():
        account_id = request.form.get("account", "")
        on = request.form.get("date", "")

        def update(state):
            state["observations"] = [
                row
                for row in state["observations"]
                if (row["account"], row["date"]) != (account_id, on)
            ]

        records.store().update(update)
        flash("Observation removed; saved baselines are unchanged.")
        return redirect(url_for("long_term_page", plan=request.form.get("plan", "")))

    @app.post("/finance/long-term/delete")
    @login_required
    def long_term_delete():
        key = request.form.get("plan", "")

        def update(state):
            if key not in state["plans"]:
                raise ValueError("Saved plan unavailable.")
            del state["plans"][key]

        try:
            records.store().update(update)
            flash("Saved baseline removed.")
        except (ValueError, OSError) as error:
            flash(str(error))
        return redirect(url_for("long_term_page"))

    @app.post("/finance/long-term/print")
    @login_required
    def long_term_print():
        from receipt.archive import load

        key = session.get("long_term_receipt")
        if not key:
            abort(400)
        item = load(key)
        if "ILLUSTRATIVE MONTHLY MODEL" not in item["pages"].get("finance", ""):
            abort(400)
        started, error = start_print(["--archive", key, "finance"])
        flash("Long-term summary queued." if started else error)
        return redirect(url_for("long_term_page"))
