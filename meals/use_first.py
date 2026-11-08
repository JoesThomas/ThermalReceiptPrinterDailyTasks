"""User-recorded fridge and freezer portions with conservative meal suggestions."""
from datetime import date
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from uuid import uuid4

from meals import household
from meals.food_storage import contains_rice
from receipt.local_time import uk_today
from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / "data" / "use_first.json"


def validate(state):
    rows = state["items"]
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Keep up to 100 saved batches.")
    ids = set()
    for row in rows:
        key = row["id"]
        if (not isinstance(key, str) or len(key) != 32 or key in ids
                or not isinstance(row["recipe"], str) or not 0 < len(row["recipe"]) <= 200
                or not isinstance(row["signature"], str)
                or type(row["portions"]) is not int or not 1 <= row["portions"] <= 100
                or row["location"] not in {"fridge", "freezer"}):
            raise ValueError("Invalid batch.")
        ids.add(key)
        cooked = date.fromisoformat(row["cooked"])
        if row["use_by"] and date.fromisoformat(row["use_by"]) < cooked:
            raise ValueError("Use-by must be on or after the cooking date.")
        if row["location"] == "fridge" and not row["use_by"]:
            raise ValueError("Enter your earlier use-by date for chilled leftovers.")


def store():
    return PrivateStore(FILE, default=lambda: {"items": []}, validate=validate, max_bytes=100_000)


def signature(recipe):
    components = household.component_foods(recipe)
    if components is None:
        return None
    ingredients, allergens = components
    return sha256(json.dumps([household.recipe_signature(recipe), ingredients, sorted(allergens)]).encode()).hexdigest()


def add(form, recipes, today=None):
    today = today or uk_today()
    recipe = recipes.get(form.get("recipe"))
    if not recipe:
        raise ValueError("Choose the recipe actually used to prepare the batch.")
    cooked = date.fromisoformat(form.get("cooked", ""))
    if cooked > today:
        raise ValueError("Cooking date cannot be in the future.")
    if form.get("confirmed") != "on":
        raise ValueError("Confirm the recipe and storage details first.")
    stamp = signature(recipe)
    if stamp is None:
        raise ValueError("Check the recipe's missing prep component before recording it.")
    row = dict(id=uuid4().hex, recipe=recipe["name"], signature=stamp,
               portions=int(form.get("portions", "0")), location=form.get("location"),
               cooked=cooked.isoformat(), use_by=form.get("use_by", ""))
    validate({"items": [row]})
    store().update(lambda state: state["items"].append(row))


def adjust(key, action):
    if action not in {"use", "remove"}:
        raise ValueError("Unknown action.")

    def change(state):
        row = next((row for row in state["items"] if row["id"] == key), None)
        if row is None:
            raise ValueError("This batch is no longer saved.")
        if action == "remove" or row["portions"] == 1:
            state["items"].remove(row)
        else:
            row["portions"] -= 1
    store().update(change)


def options(items, recipes, prefs, day):
    """Only suggest whole-household dinners, without changing the saved menu."""
    from meals.legacy_planner import _allergens
    from receipt.lifestyle import skip_meal

    s = prefs.get("_household") or household.store().read()
    if skip_meal(day) or household.attendance_paused(s, day):
        return []
    needed = ceil(sum(p["portion"] for p in household.diners(s, day, "dinner"))) if s["configured"] else 1
    if needed < 1:
        return []
    result = []
    for row in items:
        recipe = recipes.get(row["recipe"])
        if not recipe or row["signature"] != signature(recipe):
            continue
        if row["portions"] < needed or date.fromisoformat(row["cooked"]) > day:
            continue
        if row["use_by"] and date.fromisoformat(row["use_by"]) < day:
            continue
        if row["location"] == "fridge":
            # Dates have no cooking time; a same-day limit avoids assuming when
            # the rice clock started. For other food allow at most the next day.
            if (day - date.fromisoformat(row["cooked"])).days > (0 if contains_rice(recipe) else 1):
                continue
        dietary = recipe.get("dietary", {})
        if (set(prefs.get("excluded_allergens", [])) & _allergens(recipe)
                or prefs.get("vegetarian_only") and not dietary.get("vegetarian")
                or prefs.get("vegan_only") and not dietary.get("vegan")
                or not household.permitted(recipe, s, day, "dinner")):
            continue
        result.append(dict(row, needed=needed))
    return sorted(result, key=lambda row: (row["location"] != "fridge", row["use_by"] or "9999", row["cooked"]))
