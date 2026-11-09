"""Authenticated controls for the local personal helper; optional bounded errand lookups."""

import secrets
import re
import time
from datetime import date, timedelta
from threading import Lock, Thread

from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from actions import checklists
from actions import personal_helper as helper
from receipt.local_time import UK, uk_today
from storage import file_lock

GUARD = Lock()
JOB = {}


def register(app, login_required):
    def go():
        return redirect(url_for("personal_helper_page"))

    def current_task(identifier):
        row = next(
            (
                t
                for t in checklists.load()["items"]
                if t["id"] == identifier and t["kind"] == "tasks"
            ),
            None,
        )
        if not row:
            abort(404)
        return row

    def token():
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.get("/helper")
    @login_required
    def personal_helper_page():
        try:
            config = helper.store().read()
            view = helper.context()
            tasks = [
                r
                for r in checklists.load()["items"]
                if r["kind"] == "tasks" and not checklists.is_done(r)
            ]
        except (OSError, ValueError):
            abort(
                503,
                description="Personal helper data is unavailable. Check local storage before editing.",
            )
        with GUARD:
            job = dict(JOB) if JOB.get("owner") == token() else {}
        job.pop("owner", None)

        return render_template(
            "personal_helper.html",
            config=config,
            helper=view,
            tasks=tasks,
            job=job,
            clock=lambda d: d.astimezone(UK).strftime("%H:%M"),
            day=uk_today().isoformat(),
            tomorrow=(uk_today() + timedelta(days=1)).isoformat(),
            receipt_lines=helper.receipt_brief(view),
        )

    @app.post("/helper/settings")
    @login_required
    def personal_helper_settings():
        try:

            def update(s):
                s.update(
                    enabled=request.form.get("enabled") == "on",
                    compact=request.form.get("compact") == "on",
                    show_task_times=request.form.get("show_task_times") == "on",
                    start=request.form.get("start", "08:00"),
                    end=request.form.get("end", "20:00"),
                )

            helper.store().update(update)
            flash("Helper preferences saved.")
        except (OSError, ValueError):
            flash("Use valid daytime planning hours and check local storage.")
        return go()

    @app.post("/helper/receipt-priorities")
    @login_required
    def personal_helper_receipt_priorities():
        try:
            if request.form.get("action") == "reset":
                helper.store().update(lambda s: s.pop("receipt_priorities", None))
                flash("Automatic receipt priorities restored.")
            else:
                view = helper.context()
                if request.form.get("day") != view["day"]:
                    raise ValueError()
                ids = [identifier for identifier in request.form.getlist("priority") if identifier]
                available = {task["id"] for task in view["pending"]}
                if not ids or len(ids) > view["priority_limit"] or len(set(ids)) != len(ids) or not set(ids) <= available:
                    raise ValueError()
                helper.store().update(lambda s: s.update(
                    receipt_priorities={"day": view["day"], "ids": ids}
                ))
                flash("Today’s receipt priorities saved. Regenerate any saved preview.")
        except (OSError, ValueError):
            flash("Choose distinct tasks available today, or restore automatic priorities.")
        return redirect(url_for("personal_helper_page", _anchor="receipt-priorities"))

    @app.post("/helper/lighter")
    @login_required
    def personal_helper_lighter():
        day = uk_today().isoformat()

        def update(s):
            s["lighter"] = sorted(
                set(
                    (s["lighter"] + [day])
                    if request.form.get("lighter") == "on"
                    else [d for d in s["lighter"] if d != day]
                )
            )[-31:]

        helper.store().update(update)
        flash("Today’s mode updated. Deadline and essential items remain visible.")
        return go()

    @app.post("/helper/task")
    @login_required
    def personal_helper_task():
        identifier = request.form.get("task", "")
        current_task(identifier)
        try:
            raw = request.form.get("minutes", "").strip()
            minutes = int(raw) if raw else None
            steps = [
                helper.text(line, 160)
                for line in request.form.get("steps", "").splitlines()
                if line.strip()
            ]

            def update(s):
                m = s["tasks"].setdefault(
                    identifier, {"first_seen": uk_today().isoformat()}
                )
                if steps != m.get("steps", []):
                    m["step_done"] = []
                m.update(
                    minutes=minutes,
                    context=request.form.get("context", "home"),
                    effort=request.form.get("effort", "normal"),
                    essential=request.form.get("essential") == "on",
                    steps=steps,
                    hidden=False,
                    defer_until="",
                )

            helper.store().update(update)
            flash("Task estimate, context and smaller steps saved.")
        except (ValueError, OSError):
            flash("Check task minutes, context and up to ten short steps.")
        return go()

    @app.post("/helper/task-action")
    @login_required
    def personal_helper_task_action():
        identifier = request.form.get("task", "")
        row = current_task(identifier)
        action = request.form.get("action")
        if action == "complete":
            if not checklists.is_done(row):
                checklists.update("tasks", "toggle", identifier)
            flash("Task marked complete.")
            return go()
        if action not in {"defer", "tomorrow", "weekend", "hide", "step"}:
            abort(400)
        try:
            today = uk_today()
            until = None

            def update(s):
                nonlocal until
                m = s["tasks"].setdefault(
                    identifier, {"first_seen": today.isoformat()}
                )
                if action in {"defer", "tomorrow", "weekend"}:
                    if action == "tomorrow":
                        until = today + timedelta(days=1)
                    elif action == "weekend":
                        days = 1 if today.weekday() == 5 else (5 - today.weekday()) % 7
                        until = today + timedelta(days=days)
                    else:
                        until = date.fromisoformat(request.form.get("until", ""))
                    if not today < until <= today + timedelta(days=366):
                        raise ValueError()
                    m["defer_until"] = until.isoformat()
                    m["deferrals"] = sorted(
                        set(m.get("deferrals", []) + [today.isoformat()])
                    )[-30:]
                elif action == "hide":
                    m["hidden"] = True
                else:
                    index = int(request.form.get("index", ""))
                    if not 0 <= index < len(m.get("steps", [])):
                        raise ValueError()
                    done = m.setdefault("step_done", [])
                    m["step_done"] = (
                        [i for i in done if i != index]
                        if index in done
                        else done + [index]
                    )

            helper.store().update(update)
            if until:
                flash(f"Task moved to {until:%A %d %B} in the helper. Essential and due tasks still show.")
            else:
                flash("Helper task choice updated. Essential and due tasks still show.")
        except (ValueError, OSError):
            flash("This task action could not be saved.")
        return go()

    @app.post("/helper/rule")
    @login_required
    def personal_helper_rule():
        try:
            identifier = request.form.get("id") or secrets.token_hex(12)

            def update(s):
                s["rules"] = [r for r in s["rules"] if r["id"] != identifier]
                if request.form.get("remove") != "on":
                    s["rules"].append(
                        dict(
                            id=identifier,
                            match=helper.text(request.form.get("match", ""), 120),
                            lead_hours=int(request.form.get("lead_hours", "12")),
                            take=[
                                helper.text(v, 120)
                                for v in request.form.get("take", "").splitlines()
                                if v.strip()
                            ],
                            prepare=[
                                helper.text(v, 120)
                                for v in request.form.get("prepare", "").splitlines()
                                if v.strip()
                            ],
                        )
                    )

            helper.store().update(update)
            flash("Reusable packing and preparation rule saved.")
        except (OSError, ValueError):
            flash(
                "Check the event title match, lead time and up to eight short prompts."
            )
        return go()

    @app.post("/helper/errand")
    @login_required
    def personal_helper_errand():
        identifier = request.form.get("task", "")
        current_task(identifier)
        try:

            def update(s):
                if request.form.get("remove") == "on":
                    s["errands"].pop(identifier, None)
                    return
                address = helper.text(request.form.get("address", ""), 500)
                previous = s["errands"].get(identifier, {})
                s["errands"][identifier] = dict(
                    address=address,
                    point=previous.get("point")
                    if previous.get("address") == address
                    else None,
                    hours=helper.text(request.form.get("hours", ""), 160, empty=True),
                )
                s["tasks"].setdefault(identifier, {})["context"] = "outside"

            helper.store().update(update)
            flash(
                "Errand saved. Update the helper to locate it and compare your saved routes."
            )
        except (OSError, ValueError):
            flash("Check the errand address and opening-hours note.")
        return go()

    def work(owner):
        try:
            with file_lock(helper.FILE.with_name("helper_job"), blocking=False):
                config = helper.observe(checklists.load()["items"])
                deadline = time.monotonic() + 45
                from services import travel_routes
                from services.day_travel import key
                from services.day_travel import store as travel_store

                places = travel_store().read()["places"]
                updates = {}
                for identifier, errand in [
                    (k, e) for k, e in config["errands"].items() if not e.get("point")
                ][:3]:
                    with GUARD:
                        JOB["message"] = "Locating saved errand addresses…"
                    saved = places.get(key(errand["address"]))
                    if saved and saved.get("confirmed"):
                        updates[identifier] = saved["point"]
                    else:
                        resolved = travel_routes.resolve(errand["address"], deadline)
                        if resolved.get("confirmed"):
                            updates[identifier] = resolved["point"]

                def save(s):
                    for identifier, p in updates.items():
                        if (
                            identifier in s["errands"]
                            and s["errands"][identifier]["address"]
                            == config["errands"][identifier]["address"]
                        ):
                            s["errands"][identifier]["point"] = p

                if updates:
                    helper.store().update(save)
            with GUARD:
                JOB.update(
                    state="complete",
                    message="Helper updated. Routes and calendar are read from your saved plans.",
                )
        except Exception:
            with GUARD:
                JOB.update(
                    state="failed",
                    message="Helper refresh unavailable. Check local data and connections; no missing route is treated as a match.",
                )

    @app.post("/helper/refresh")
    @login_required
    def personal_helper_refresh():
        with GUARD:
            if JOB.get("state") == "running":
                abort(409)
            JOB.clear()
            JOB.update(
                owner=token(),
                state="running",
                message="Updating observations and errand locations…",
            )
        Thread(target=work, args=(token(),), daemon=True).start()
        return go()

    @app.get("/helper/status")
    @login_required
    def personal_helper_status():
        with GUARD:
            value = dict(JOB) if JOB.get("owner") == token() else {}
        value.pop("owner", None)
        return jsonify(value)

    @app.post("/helper/meal-quantity")
    @login_required
    def personal_helper_meal_quantity():
        from meals import legacy_planner as meals
        from meals.ingredients import parse
        from meals.resource_planning import component_ids

        name, cid = request.form.get("recipe", ""), request.form.get("component", "")
        recipe = next((r for r in meals.recipes() if r.get("name") == name), None)
        components = meals._load(meals.COMPONENTS_FILE, {}).get("components", [])
        component = next((c for c in components if c.get("id") == cid), None)
        if not recipe or not component or cid not in component_ids(recipe):
            abort(400)
        try:
            quantity = helper.text(request.form.get("quantity", ""), 80, empty=True)
            parsed = parse(quantity + " " + component["name"]) if quantity else None
            if quantity and (
                not re.fullmatch(
                    r"(?:\d+ \d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(?:kg|g|ml|l|tsp|tbsp)",
                    quantity,
                    re.I,
                )
                or not parsed
                or parsed[0] <= 0
                or parsed[1] not in {"g", "kg", "ml", "l", "tsp", "tbsp"}
            ):
                raise ValueError()

            def save(s):
                key = name + "|" + cid
                if quantity:
                    s["meal_uses"][key] = quantity
                else:
                    s["meal_uses"].pop(key, None)

            helper.store().update(save)
            flash(
                "Component amount saved for this recipe; totals update across its planned uses."
            )
        except (ValueError, OSError):
            flash(
                "Use a positive amount and unit, for example 2 tbsp or 100 g. Leave blank to reset."
            )
        return redirect(url_for("meals_page", _anchor="meal-resources"))

    @app.context_processor
    def navigation():
        return {"personal_helper_available": True}
