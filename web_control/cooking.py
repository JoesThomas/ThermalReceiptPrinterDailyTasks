"""Touch-friendly view of the recipes used by the meal planner and receipt."""

from flask import render_template, request

from meals import household, legacy_planner as planner
from meals.diet_handling import guidance
from receipt.build_info import fingerprint
from receipt.local_time import uk_today


def register(app, login_required):
    from meals.ingredients import ingredient_display

    app.jinja_env.filters["ingredient_display"] = ingredient_display

    @app.get("/meals/cook")
    @login_required
    def cooking_page():
        today = uk_today()
        choice = request.args.get("recipe", "")
        recipe, problem = None, None
        options, handling = [], None
        status = 200
        try:
            prefs = planner.preferences()
            handling = guidance(prefs)
            eligible = {
                row["name"]: row for row in planner.recipes()
                if row.get("name") and row.get("method") and planner._eligible(row, today, prefs)
            }
            options = sorted(eligible, key=str.casefold)
            if choice:
                if choice in eligible:
                    recipe = household.prepare(eligible[choice], today, prefs.get("_household"))
                else:
                    problem = "That recipe is unavailable for the current meal settings. Choose another recipe."
                    status = 400
            else:
                planned = planner.get_meal(today)
                if planned and planned["kind"] == "recipe":
                    recipe = planned["recipe"]
                else:
                    problem = planned.get("name") if planned else "No recipe is planned today."
        except (OSError, ValueError, RuntimeError):
            problem = "The recipe could not be loaded. Check your meal settings and saved plan."
            status = 503
        if recipe and not recipe.get("method"):
            recipe = None
            problem = "This recipe has no method. Choose another recipe."
        ingredients = recipe.get("ingredients", []) if recipe else []
        method = recipe.get("method", []) if recipe else []
        return render_template(
            "cooking.html", recipe=recipe, ingredients=ingredients, method=method, options=options,
            choice=choice, today=today, problem=problem, handling=handling,
            allergens=sorted(planner._allergens(recipe)) if recipe else [],
            progress_key=fingerprint([today.isoformat(), recipe["name"], ingredients, method]) if recipe else "",
        ), status
