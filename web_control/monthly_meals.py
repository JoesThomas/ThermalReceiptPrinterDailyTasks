"""Login/CSRF-protected monthly meal planning and local shop preferences."""

from flask import abort, flash, redirect, render_template, request, url_for
from meals import monthly, legacy_planner as planner, supermarket
from receipt.local_time import uk_today


def register(app, login_required):
    def selected():
        raw = request.values.get("month", uk_today().strftime("%Y-%m"))
        try:
            first, last = monthly.bounds(raw)
            if abs((first - uk_today()).days) > 400:
                raise ValueError()
        except (ValueError, TypeError):
            abort(400, description="Choose a month within one year of today.")
        return raw

    def go(raw):
        return redirect(url_for("monthly_meals_page", month=raw))

    def sync_tasks(raw):
        from meals.shopping_tasks import sync

        try:
            sync(raw, uk_today())
        except (OSError, ValueError, RuntimeError):
            flash(
                "The meal change was saved, but shopping tasks could not be updated. Check your task list."
            )

    @app.get("/meals/month")
    @login_required
    def monthly_meals_page():
        raw = selected()
        try:
            view = monthly.report(raw)
        except (OSError, ValueError):
            abort(
                503,
                description="Monthly meal data is unavailable. Check local files before creating or changing plans.",
            )
        return render_template(
            "monthly_meals.html",
            view=view,
            categories=monthly.CATEGORIES,
            shops=monthly.SHOPS,
            weekdays=[
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ],
            recipes=planner.recipes(),
            retailers=supermarket.RETAILERS,
            local_shops=monthly.LOCAL_SHOPS,
        )

    @app.post("/meals/month/generate")
    @login_required
    def monthly_meals_generate():
        raw = selected()
        try:
            count = monthly.generate(raw)
            sync_tasks(raw)
            flash(
                f"Month ready: {count} week(s) created or completed. Existing meals were kept; the daily receipt uses these same plans."
            )
        except (ValueError, RuntimeError, OSError):
            flash(
                "Could not finish the month. Check recipe eligibility and saved files. Existing weeks are kept; retry to fill any missing weeks."
            )
        return go(raw)

    @app.post("/meals/month/settings")
    @login_required
    def monthly_meals_settings():
        raw = selected()
        try:

            def save(s):
                s.update(
                    retailer=request.form.get("retailer", s.get("retailer", "tesco")),
                    weekly_day=int(request.form.get("weekly_day", "5")),
                    veg_topup=request.form.get("veg_topup") == "on",
                    veg_day=int(request.form.get("veg_day", "2")),
                    shops={
                        category: request.form.get("shop_" + str(i), "")
                        for i, category in enumerate(monthly.CATEGORIES)
                    },
                )

            monthly.store().update(save)
            sync_tasks(raw)
            flash(
                "Shopping days and suppliers saved. Lists regroup without changing the menu."
            )
        except (ValueError, OSError):
            flash(
                "Check the weekdays, supermarket and shop choices. Fresh categories must stay on weekly lists."
            )
        return go(raw)

    @app.post("/meals/month/attendance")
    @login_required
    def monthly_meals_attendance():
        from datetime import date, timedelta
        from meals import household

        raw = selected()
        try:
            day = date.fromisoformat(request.form.get("day", ""))
            first, last = monthly.bounds(raw)
            on = uk_today()
            if not max(on, first) <= day <= last:
                raise ValueError("Choose today or an upcoming day in this month.")
            checked = set(request.form.getlist("absent"))

            def save(s):
                if not s["configured"]:
                    raise ValueError("Set up household profiles first.")
                people = household.people_by_id(s)
                valid = {
                    f"{key}:{slot}" for key in people for slot in household.MEAL_SLOTS
                }
                if not checked <= valid:
                    raise ValueError(
                        "Household profiles changed. Refresh and try again."
                    )
                value = {
                    key: [
                        slot
                        for slot in household.MEAL_SLOTS
                        if f"{key}:{slot}" in checked
                    ]
                    for key in people
                }
                cutoff = (on - timedelta(days=365)).isoformat()
                absences = {
                    d: a for d, a in s.get("absences", {}).items() if d >= cutoff
                }
                absences.pop(day.isoformat(), None)
                if any(value.values()):
                    absences[day.isoformat()] = {
                        key: slots for key, slots in value.items() if slots
                    }
                s["absences"] = absences

            household.store().update(save)
            sync_tasks(raw)
            # Lunch is prepared with the previous evening's dinner.
            if day == first:
                previous = (first - timedelta(days=1)).strftime("%Y-%m")
                sync_tasks(previous)
            flash(
                "Attendance saved. Meal portions and shopping now use the updated numbers."
            )
        except (ValueError, OSError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Could not save attendance."
            )
        return redirect(
            url_for(
                "monthly_meals_page",
                month=raw,
                _anchor="day-" + request.form.get("day", "")[:10],
            )
        )

    @app.route("/meals/shop", methods=["GET", "POST"])
    @login_required
    def meal_shop():
        raw = selected()
        try:
            view = monthly.report(raw)
        except (OSError, ValueError):
            abort(
                503,
                description="The meal shopping list is unavailable. Check local meal data.",
            )
        supplier = request.values.get("supplier", "")
        if supplier and supplier not in monthly.LOCAL_SHOPS:
            abort(400, description="Choose a scheduled local supplier.")
        if supplier and request.method == "POST":
            abort(405)
        retailer = view["config"].get("retailer", "tesco")
        name = supermarket.RETAILERS[retailer][0]
        allowed = (supplier,) if supplier else monthly.SUPERMARKET_SHOPS
        scheduled = [visit for visit in view["visits"] if visit["shop"] in allowed]
        dates = sorted({visit["day"].isoformat() for visit in scheduled})
        day = request.values.get("day", dates[0] if dates else "")
        if day and day not in dates:
            flash("That shopping date is no longer available. Select a current list.")
            return redirect(url_for("meal_shop", month=raw, supplier=supplier or None))
        visits = [v for v in scheduled if v["day"].isoformat() == day]
        rows, fingerprint = supermarket.review(visits, None if supplier else retailer)
        enabled = not supplier and supermarket.available(retailer)
        checked = {r["id"] for r in rows if r["measured"] and not r["pantry"]}
        landing = None
        if request.method == "POST":
            chosen = set(request.form.getlist("item"))
            valid = {r["id"] for r in rows}
            if request.form.get("fingerprint") != fingerprint or not chosen <= valid:
                flash(
                    "The shopping list or supermarket changed. Review the current list before sending."
                )
            else:
                checked = chosen
                try:
                    if request.form.get("confirm_share") != "yes":
                        raise supermarket.HandoffError(
                            "Confirm that you want to send the selected ingredients."
                        )
                    landing = supermarket.transfer(
                        retailer, [r["amount"] for r in rows if r["id"] in chosen]
                    )
                except supermarket.HandoffError as error:
                    flash(str(error))
        return render_template(
            "meal_shop.html",
            view=view,
            day=day,
            dates=dates,
            visits=visits,
            supplier=supplier,
            retailer=retailer,
            retailer_name=name,
            retailer_home=supermarket.SHOPS_HOME[retailer],
            partner_supported=bool(supermarket.RETAILERS[retailer][3]),
            enabled=enabled,
            rows=rows,
            checked=checked,
            fingerprint=fingerprint,
            landing=landing,
        )

    @app.post("/meals/month/ingredient")
    @login_required
    def monthly_meals_ingredient():
        raw = selected()
        try:
            key = request.form.get("ingredient", "")
            kind = request.form.get("category", "")
            view = monthly.report(raw)
            if key not in {i["key"] for i in view["ingredients"]}:
                abort(400)

            def save(s):
                if kind == "default":
                    s["overrides"].pop(key, None)
                else:
                    s["overrides"][key] = kind

            monthly.store().update(save)
            sync_tasks(raw)
            flash(
                "Ingredient category saved for future shopping lists too. Check packaging before assigning something to the monthly cupboard/freezer shop."
            )
        except (ValueError, OSError):
            flash("Could not save this ingredient choice.")
        return go(raw)

    @app.post("/meals/month/meal")
    @login_required
    def monthly_meals_meal():
        raw = selected()
        try:
            monthly.change_meal(
                raw, request.form.get("day", ""), request.form.get("recipe", "")
            )
            sync_tasks(raw)
            flash(
                "Meal changed. Monthly shopping and the daily receipt now use the updated week."
            )
        except (ValueError, OSError):
            flash(
                "Choose an upcoming, uneaten day and an eligible recipe from a saved week."
            )
        return go(raw)

    @app.context_processor
    def monthly_navigation():
        return {"monthly_meals_available": True}
