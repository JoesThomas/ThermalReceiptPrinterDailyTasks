"""Private household profiles, meal choices and emergency-food preferences."""

from datetime import date, timedelta
import secrets
from flask import abort, flash, redirect, render_template, request, url_for
from meals import household, breakfast, emergency_food, nutrition_guidance
from receipt.local_time import uk_today


def register(app, login_required):
    def go():
        return redirect(url_for("meal_settings_page"))

    def lines(raw, limit=80):
        return [
            household.label(v.strip(), limit) for v in raw.splitlines() if v.strip()
        ]

    @app.get("/meals/settings")
    @login_required
    def meal_settings_page():
        from meals import legacy_planner

        try:
            s = household.store().read()
            today = uk_today()
            references = [
                dict(person=p, **nutrition_guidance.energy(p, today))
                for p in s["people"]
            ]
            return render_template(
                "meal_settings.html",
                config=s,
                references=references,
                dinners=legacy_planner.recipes(),
                breakfasts=breakfast.catalogue(today, s),
                allergens=household.ALLERGENS,
                reserve=emergency_food.report(today, s),
                today=today,
                person_template=dict(household.person(), name="Person __number__"),
                energy_source=nutrition_guidance.ENERGY_SOURCE,
                balance_source=nutrition_guidance.BALANCE_SOURCE,
                season_source=nutrition_guidance.SEASON_SOURCE,
            )
        except (ValueError, OSError):
            abort(
                503,
                description="Household meal settings are unavailable. Restore valid local data before editing.",
            )

    @app.post("/meals/settings/household")
    @login_required
    def meal_settings_save():
        try:
            indices = request.form.getlist("person_index")
            if (
                not 1 <= len(indices) <= 20
                or len(set(indices)) != len(indices)
                or any(not i.isdigit() or len(i) > 5 for i in indices)
            ):
                raise ValueError()
            people = []
            for n, i in enumerate(indices):
                raw = request.form.get("birth_year_" + i, "").strip()
                people.append(
                    dict(
                        name=household.label(
                            request.form.get("person_name_" + i, ""), 80
                        )
                        or f"Person {n + 1}",
                        birth_year=int(raw) if raw else None,
                        reference=request.form.get("reference_" + i, "range"),
                        diet=request.form.get("diet_" + i, "omnivore"),
                        allergens=request.form.getlist("allergen_" + i),
                        avoid=lines(request.form.get("avoid_" + i, "")),
                        clinical=request.form.get("clinical_" + i) == "on",
                        notes=household.label(request.form.get("notes_" + i, ""), 300),
                        portion=float(request.form.get("portion_" + i, "1")),
                    )
                )

            def save(s):
                s.update(
                    configured=True,
                    people=people,
                    balanced=request.form.get("balanced") == "on",
                    seasonal=request.form.get("seasonal") == "on",
                    breakfast_enabled=request.form.get("breakfast_enabled") == "on",
                    weekday_minutes=int(request.form.get("weekday_minutes", "5")),
                    weekend_minutes=int(request.form.get("weekend_minutes", "25")),
                    eating_minutes=int(request.form.get("eating_minutes", "15")),
                    breakfast_start=request.form.get("breakfast_start", "07:00"),
                    breakfast_end=request.form.get("breakfast_end", "10:00"),
                    provisional_weekends=request.form.get("provisional_weekends")
                    == "on",
                    dinners=None
                    if request.form.get("all_dinners") == "on"
                    else request.form.getlist("dinner"),
                    breakfasts=None
                    if request.form.get("all_breakfasts") == "on"
                    else request.form.getlist("breakfast"),
                )

            household.store().update(save)
            flash(
                "Household preferences saved. New choices and quantities use these settings. Complete the monthly menu to replace incompatible future recipes; past and eaten meals stay recorded."
            )
        except (ValueError, OSError):
            flash(
                "Check the household profiles, birth years, portion factors and time limits. Keep at least one enabled breakfast and dinner, or choose all."
            )
        return go()

    @app.post("/meals/settings/recipe")
    @login_required
    def meal_settings_recipe():
        from meals import legacy_planner

        try:
            identifier = request.form.get("id") or secrets.token_hex(12)
            name = household.label(request.form.get("name", ""), 120)

            def save(s):
                old = next((r for r in s["custom"] if r["id"] == identifier), None)
                if request.form.get("remove") == "on":
                    if not old:
                        raise ValueError()
                    s["custom"] = [r for r in s["custom"] if r["id"] != identifier]
                    for key in ("dinners", "breakfasts"):
                        if s[key] is not None and old["name"] in s[key]:
                            s[key] = [n for n in s[key] if n != old["name"]]
                    return
                if not name or any(
                    r["name"].casefold() == name.casefold()
                    for r in legacy_planner.recipes() + breakfast.catalogue()
                    if r.get("id") != identifier
                ):
                    raise ValueError()
                vegan = request.form.get("vegan") == "on"
                raw = request.form.get("calories", "").strip()
                kcal = int(raw) if raw else None
                if kcal is not None and not 0 < kcal <= 3000:
                    raise ValueError()
                r = dict(
                    id=identifier,
                    name=name,
                    slot=request.form.get("slot", "dinner"),
                    ingredients=lines(request.form.get("ingredients", ""), 300),
                    method=lines(request.form.get("method", ""), 300),
                    total_minutes=int(request.form.get("minutes", "20")),
                    cook_servings=float(request.form.get("servings", "1")),
                    servings=1,
                    meal_type="single",
                    allergens={"uk_14": request.form.getlist("recipe_allergen")},
                    dietary={
                        "vegan": vegan,
                        "vegetarian": vegan or request.form.get("vegetarian") == "on",
                    },
                    nutrition_per_serving={"calories": kcal},
                    prep_components=[],
                )
                s["custom"] = [
                    item for item in s["custom"] if item["id"] != identifier
                ] + [r]
                if old:
                    for key in ("dinners", "breakfasts"):
                        if s[key] is not None:
                            s[key] = [name if v == old["name"] else v for v in s[key]]

            household.store().update(save)
            flash(
                "Custom recipe updated. Confirm ingredient labels and method details before using it."
            )
        except (ValueError, OSError):
            flash(
                "Check the recipe name, meal type, yield, ingredients, method and optional energy estimate. Enable another meal before deleting your only selected option."
            )
        return go()

    @app.post("/meals/settings/reserve")
    @login_required
    def meal_settings_reserve():
        try:
            ids = {r["id"] for r in emergency_food.catalogue()}

            def save(s):
                s.update(
                    reserve_days=int(request.form.get("reserve_days", "3")),
                    water_litres=float(request.form.get("water_litres", "3")),
                    water_have=float(request.form.get("water_have", "0")),
                    reserve_notes=household.label(
                        request.form.get("reserve_notes", ""), 500
                    ),
                )
                for key in ids:
                    target = request.form.get("target_" + key, "").strip()
                    have = request.form.get("have_" + key, "").strip()
                    if target:
                        s["reserve_targets"][key] = float(target)
                    else:
                        s["reserve_targets"].pop(key, None)
                    if have:
                        s["reserve_have"][key] = float(have)

            household.store().update(save)
            flash(
                "Your reserve goals and stock notes were saved. Food quantities are your choices, not government-prescribed pack counts."
            )
        except (ValueError, OSError):
            flash("Check reserve days and non-negative stock quantities.")
        return go()

    @app.post("/meals/breakfast")
    @login_required
    def meal_breakfast_change():
        try:
            on = date.fromisoformat(request.form.get("day", ""))
            if abs((on - uk_today()).days) > 400:
                raise ValueError()
            action = request.form.get("action", "choose")

            def save(s):
                if action in ("eaten", "undo"):
                    if on > uk_today():
                        raise ValueError()
                    s["breakfast_done"] = sorted(
                        (set(s["breakfast_done"]) | {on.isoformat()})
                        if action == "eaten"
                        else (set(s["breakfast_done"]) - {on.isoformat()})
                    )[-400:]
                elif action == "choose":
                    name = request.form.get("breakfast", "")
                    if name:
                        r = next(
                            (
                                r
                                for r in breakfast.catalogue(on, s)
                                if r["name"] == name
                            ),
                            None,
                        )
                        from meals import legacy_planner

                        if (
                            not r
                            or not household.permitted(r, s, on, "breakfast")
                            or not legacy_planner._eligible(
                                r, on, legacy_planner.preferences(), slot="breakfast"
                            )
                        ):
                            raise ValueError()
                        s["breakfast_overrides"][on.isoformat()] = name
                    else:
                        s["breakfast_overrides"].pop(on.isoformat(), None)
                else:
                    raise ValueError()

            household.store().update(save)
            flash("Breakfast choice updated. Shopping uses the same current choice.")
        except (ValueError, OSError):
            flash(
                "Choose a valid day and an enabled, eligible breakfast. Only meals already due can be marked eaten."
            )
        raw = request.form.get("month", "")
        if raw:
            from meals.monthly import bounds

            try:
                bounds(raw)
                return redirect(url_for("monthly_meals_page", month=raw))
            except ValueError:
                pass
        return redirect(url_for("meals_page"))

    @app.context_processor
    def meal_settings_navigation():
        return {"household_meals_available": True}
