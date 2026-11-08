from datetime import date, timedelta
from flask import flash, redirect, render_template, request, url_for

from meals import legacy_planner as planner, use_first as batches
from receipt.local_time import uk_today


def register(app, login_required):
    @app.context_processor
    def use_first_context():
        return {"use_first_available": True}

    @app.route("/meals/use-first", methods=["GET", "POST"])
    @login_required
    def use_first():
        today = uk_today()
        try:
            day = date.fromisoformat(request.values.get("day", today.isoformat()))
            if not today <= day <= today + timedelta(days=62):
                raise ValueError()
        except ValueError:
            day = today
        recipes = {recipe["name"]: recipe for recipe in planner.recipes() if recipe.get("name")}
        if request.method == "POST":
            try:
                action = request.form.get("action")
                if action == "add":
                    batches.add(request.form, recipes, today)
                else:
                    batches.adjust(request.form.get("id"), action)
                flash("Batch updated.")
            except ValueError as error:
                flash(str(error))
            except OSError:
                flash("Could not save the batch.")
            return redirect(url_for("use_first", day=day.isoformat()))
        try:
            items = batches.store().read()["items"]
            options = batches.options(items, recipes, planner.preferences(), day)
        except (OSError, ValueError):
            items, options = [], []
            flash("Saved batches or meal preferences could not be read.")
        from meals.food_storage import FRIDGE, LABEL, REHEAT, THAW
        return render_template("use_first.html", day=day, today=today, latest=today + timedelta(days=62),
                               items=items, options=options, recipes=sorted(recipes),
                               guidance=[FRIDGE, THAW, REHEAT, LABEL])
