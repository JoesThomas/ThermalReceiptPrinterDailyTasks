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
            flash(
                "Shopping days and suppliers saved. Lists regroup without changing the menu."
            )
        except (ValueError, OSError):
            flash(
                "Check the weekdays, supermarket and shop choices. Fresh categories must stay on weekly lists."
            )
        return go(raw)

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
        retailer = view["config"].get("retailer", "tesco")
        name = supermarket.RETAILERS[retailer][0]
        dates = sorted({visit["day"].isoformat() for visit in view["visits"]})
        day = request.values.get("day", dates[0] if dates else "")
        if day and day not in dates:
            flash("That shopping date is no longer available. Select a current list.")
            return redirect(url_for("meal_shop", month=raw))
        visits = [v for v in view["visits"] if v["day"].isoformat() == day]
        rows, fingerprint = supermarket.review(visits, retailer)
        enabled = supermarket.available(retailer)
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
