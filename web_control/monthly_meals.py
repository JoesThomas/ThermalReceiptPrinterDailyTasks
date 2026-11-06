"""Login/CSRF-protected monthly meal planning and local shop preferences."""

from flask import abort, flash, redirect, render_template, request, url_for
from meals import monthly, legacy_planner as planner
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
        )

    @app.post("/meals/month/generate")
    @login_required
    def monthly_meals_generate():
        raw = selected()
        try:
            count = monthly.generate(raw)
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
                    weekly_day=int(request.form.get("weekly_day", "5")),
                    veg_topup=request.form.get("veg_topup") == "on",
                    veg_day=int(request.form.get("veg_day", "2")),
                    shops={
                        category: request.form.get("shop_" + str(i), "")
                        for i, category in enumerate(monthly.CATEGORIES)
                    },
                )

            monthly.store().update(save)
            flash(
                "Shopping days and suppliers saved. Lists regroup without changing the menu."
            )
        except (ValueError, OSError):
            flash(
                "Check the weekdays and shop choices. Fresh categories must stay on weekly lists."
            )
        return go(raw)

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
