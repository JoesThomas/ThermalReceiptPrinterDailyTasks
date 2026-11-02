"""Authenticated daily itinerary with bounded background lookups and local home settings."""

from copy import deepcopy
from datetime import date, datetime
import secrets
from threading import Lock, Thread
import time
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
from services import day_travel as travel
from services import travel_routes as provider
from storage import file_lock

GUARD = Lock()
JOB = {}


def register(app, login_required, collect, transit_credentials=lambda: ("", "")):
    def selected():
        from receipt.local_time import uk_today

        value = request.values.get("day", uk_today().isoformat())
        try:
            chosen = date.fromisoformat(value)
            if abs((chosen - uk_today()).days) > 366:
                raise ValueError()
        except (ValueError, TypeError):
            abort(400, description="Choose a date within one year of today.")
        return chosen.isoformat()

    def owner():
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    def go(day):
        return redirect(url_for("day_travel", day=day))

    @app.after_request
    def private_travel(response):
        if request.path.startswith("/day-travel"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/day-travel")
    @login_required
    def day_travel():
        day = selected()
        owner()
        try:
            state = travel.store().read()
        except (ValueError, OSError):
            abort(
                503,
                description="Travel settings are unavailable. Check local private storage.",
            )
        day_data = state["days"].get(day, dict(events=[], overrides={}))
        places = []
        addresses = [state["home"]] + [e["address"] for e in day_data["events"]]
        for address in dict.fromkeys(addresses):
            if address:
                identifier = travel.key(address)
                places.append(
                    dict(
                        id=identifier,
                        address=address,
                        **{
                            k: v
                            for k, v in state["places"].get(identifier, {}).items()
                            if k != "address"
                        },
                    )
                )
        with GUARD:
            job = (
                deepcopy(JOB)
                if JOB.get("owner") == owner() and JOB.get("day") == day
                else {}
            )
        job.pop("owner", None)
        from receipt.local_time import uk_receipt_time

        def journey_time(raw):
            dt = travel.when(raw)
            return (
                dt.strftime(
                    "%H:%M %Z" if dt.date().isoformat() == day else "%d %b %H:%M %Z"
                )
                if dt
                else "Unknown"
            )

        return render_template(
            "day_travel.html",
            day=day,
            travel_settings={
                **state,
                "mode": state["mode"] if "walk_minutes" in state else "auto",
            },
            transit_connected=all(transit_credentials()),
            day_data=day_data,
            places=places,
            travel_job=job,
            travel_time=uk_receipt_time,
            journey_time=journey_time,
        )

    @app.post("/day-travel/settings")
    @login_required
    def day_travel_settings():
        day = selected()
        try:
            home = travel.text(request.form.get("home", ""))
            mode = request.form.get("mode", "driving")
            if mode not in travel.MODES:
                raise ValueError("Choose a travel mode.")
            values = dict(
                home=home,
                mode=mode,
                car=request.form.get("car") == "on",
                walk_minutes=travel.integer(
                    request.form.get("walk_minutes", "25"), 0, 120
                ),
                buffer=travel.integer(request.form.get("buffer"), 0, 120),
                home_minutes=travel.integer(request.form.get("home_minutes"), 0, 480),
                parking=travel.integer(request.form.get("parking"), 0, 60),
            )

            def change(s):
                if not home:
                    raise ValueError("Enter a home location.")
                s.update(values)
                s["places"].setdefault(
                    travel.key(home),
                    dict(address=home, choices=[], confirmed=False, point=None),
                )
                for row in s["days"].values():
                    row.pop("plan", None)

            travel.store().update(change)
            flash(
                "Home and travel preferences saved locally. Rebuild the plan after changes."
            )
        except (ValueError, OSError):
            flash("Settings could not be saved. Check the fields and local storage.")
        return go(day)

    @app.post("/day-travel/place")
    @login_required
    def day_travel_place():
        day = selected()
        try:
            identifier = request.form.get("place", "")

            def change(s):
                place = s["places"].get(identifier)
                if not place:
                    raise ValueError("Find locations first.")
                if request.form.get("latitude") or request.form.get("longitude"):
                    coords = travel.point(
                        [
                            float(request.form.get("latitude", "")),
                            float(request.form.get("longitude", "")),
                        ]
                    )
                else:
                    index = travel.integer(request.form.get("choice"), 0, 2)
                    coords = place.get("choices", [])[index]["point"]
                place.update(
                    point=coords,
                    confirmed=True,
                    source="Your map correction",
                    accuracy="",
                )
                for row in s["days"].values():
                    row.pop("plan", None)

            travel.store().update(change)
            flash("Map point confirmed locally.")
        except (ValueError, OSError, IndexError):
            flash("Choose a location result or enter valid coordinates.")
        return go(day)

    @app.post("/day-travel/event")
    @login_required
    def day_travel_event():
        day = selected()
        try:
            identity = request.form.get("event", "")
            mode = request.form.get("mode", "auto")
            via = request.form.get("via", "auto")
            end = request.form.get("end", "")
            if mode not in travel.MODES or via not in {"auto", "home", "direct"}:
                raise ValueError()
            if end:
                time.strptime(end, "%H:%M")

            def change(s):
                row = s["days"][day]
                if not any(e["id"] == identity for e in row["events"]):
                    raise ValueError()
                row.setdefault("overrides", {})[identity] = dict(
                    mode=mode, via=via, end=end, skip=request.form.get("skip") == "on"
                )
                row.pop("plan", None)

            travel.store().update(change)
            flash("Journey choice saved. Rebuild the plan to apply it.")
        except (ValueError, OSError, KeyError):
            flash("Event travel choice could not be saved.")
        return go(day)

    @app.post("/day-travel/duration")
    @login_required
    def day_travel_duration():
        day = selected()
        try:
            a = request.form.get("origin", "")
            b = request.form.get("destination", "")
            mode = request.form.get("mode", "transit")
            if mode not in travel.MODES - {"auto"}:
                raise ValueError()
            remove = request.form.get("remove") == "on"
            minutes = (
                travel.integer(request.form.get("minutes"), 0, 1440)
                if not remove
                else None
            )

            def change(s):
                if a not in s["places"] or b not in s["places"]:
                    raise ValueError()
                route_id = "|".join((a, b, mode))
                if remove:
                    s["manual"].pop(route_id, None)
                else:
                    s["manual"][route_id] = minutes
                for row in s["days"].values():
                    row.pop("plan", None)

            travel.store().update(change)
            flash(
                "One-way duration saved. Include waiting and changes for public transport; rebuild your plan."
            )
        except (ValueError, OSError):
            flash("Duration could not be saved.")
        return go(day)

    @app.post("/day-travel/clear")
    @login_required
    def day_travel_clear():
        if request.form.get("confirm") != "on":
            abort(400)

        def change(s):
            s.clear()
            s.update(travel.defaults())

        with GUARD:
            if JOB.get("state") == "running":
                abort(
                    409,
                    description="Wait for the active travel request before clearing its data.",
                )
            with file_lock(travel.FILE.with_name("day_travel_job"), blocking=False):
                travel.store().update(change)
                for path in provider.CACHE.glob("*.json"):
                    path.unlink(missing_ok=True)
                JOB.clear()
        flash(
            "Saved travel data and provider cache removed. External provider logs and separate copies are unaffected."
        )
        return go(selected())

    def update(message):
        with GUARD:
            JOB["message"] = message

    def work(day, action, identity, token):
        try:
            # Nonblocking installation lock: never queue a second network-heavy planner.
            with file_lock(travel.FILE.with_name("day_travel_job"), blocking=False):
                state = travel.store().read()
                deadline = time.monotonic() + 120
                if action in {"locations", "auto"}:
                    update("Retrieving the selected day’s calendar…")
                    events, warnings = collect(date.fromisoformat(day))
                    rows = travel.event_rows(events, day)
                    addresses = list(
                        dict.fromkeys(
                            [state["home"]]
                            + [e["address"] for e in rows if e["address"]]
                        )
                    )
                    places = {}
                    for index, address in enumerate(addresses):
                        if not address:
                            continue
                        identifier = travel.key(address)
                        if state["places"].get(identifier, {}).get("confirmed"):
                            continue
                        update(f"Finding location {index + 1} of {len(addresses)}…")
                        try:
                            places[identifier] = provider.resolve(address, deadline)
                        except Exception:
                            places[identifier] = dict(
                                address=address,
                                choices=[],
                                confirmed=False,
                                point=None,
                                source="Lookup unavailable",
                                accuracy="",
                            )

                    def save(s):
                        if s["home"] != state["home"]:
                            raise ValueError("Settings changed; retry.")
                        old = s["days"].get(day, {})
                        s["days"][day] = dict(
                            events=rows,
                            overrides={
                                k: v
                                for k, v in old.get("overrides", {}).items()
                                if k in {e["id"] for e in rows}
                            },
                            warnings=warnings,
                            checked=datetime.now(travel.UK).isoformat(),
                        )
                        for k, v in places.items():
                            if not s["places"].get(k, {}).get("confirmed"):
                                s["places"][k] = v
                        # A small rolling cache, not a location history archive.
                        for old_day in sorted(s["days"])[:-31]:
                            s["days"].pop(old_day)

                    with GUARD:
                        if JOB.get("token") != token:
                            raise ValueError("Request was cancelled.")
                        travel.store().update(save)
                if action in {"plan", "auto"}:
                    state = travel.store().read()
                    update(
                        "Comparing walking, bus/train journeys, home stops and parked-car locations…"
                    )
                    from services import travel_transit

                    account = transit_credentials()
                    requests_left = [24]

                    def public_route(a, b, **times):
                        if requests_left[0] <= 0 or time.monotonic() >= deadline:
                            return None
                        requests_left[0] -= 1
                        return travel_transit.route(a, b, deadline, account, **times)

                    plan = travel.build(
                        state,
                        day,
                        lambda a, b, m: provider.route(a, b, m, deadline),
                        update,
                        transit=public_route if all(account) else None,
                    )
                    plan["transit_connected"] = all(account)
                    if not all(account):
                        plan["warnings"].append(
                            "Public transport is not connected. Add TransportAPI journey-planner access once to retrieve bus/train times automatically; walking and driving still work."
                        )
                    elif requests_left[0] <= 0:
                        plan["warnings"].append(
                            "Public transport lookup limit reached for this plan. Some alternatives may be unavailable; retry the selected journeys separately."
                        )
                    plan["checked"] = datetime.now(travel.UK).isoformat()

                    def save(s):
                        if s != state:
                            raise ValueError("Settings changed; rebuild the plan.")
                        s["days"].setdefault(day, dict(events=[], overrides={}))[
                            "plan"
                        ] = plan

                    with GUARD:
                        if JOB.get("token") != token:
                            raise ValueError("Request was cancelled.")
                        travel.store().update(save)
            with GUARD:
                if JOB.get("owner") == identity and JOB.get("token") == token:
                    JOB.update(
                        state="complete",
                        message="Locations ready to confirm."
                        if action == "locations"
                        else "Day plan ready.",
                    )
        except Exception:
            with GUARD:
                if JOB.get("owner") == identity and JOB.get("token") == token:
                    JOB.update(
                        state="failed",
                        message="Travel update unavailable. Check calendar/provider connectivity or changed settings, then try again. No missing duration is treated as zero.",
                    )

    @app.post("/day-travel/run")
    @login_required
    def day_travel_run():
        day = selected()
        identity = owner()
        action = request.form.get("action")
        if action not in {"locations", "plan", "auto"}:
            abort(400)
        with GUARD:
            if JOB.get("state") == "running":
                abort(409, description="A day travel request is already running.")
            token = secrets.token_hex(16)
            JOB.clear()
            JOB.update(
                owner=identity,
                token=token,
                day=day,
                state="running",
                message="Starting travel update…",
            )
        Thread(target=work, args=(day, action, identity, token), daemon=True).start()
        return go(day)

    @app.get("/day-travel/status")
    @login_required
    def day_travel_status():
        with GUARD:
            result = deepcopy(JOB) if JOB.get("owner") == owner() else {}
        result.pop("owner", None)
        result.pop("token", None)
        return jsonify(result)

    @app.context_processor
    def links():
        return {"day_travel_available": True}
