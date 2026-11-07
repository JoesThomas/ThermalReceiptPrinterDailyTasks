"""Local household preferences; safe filtering and explicit recipe-quantity scaling."""

from copy import deepcopy
from datetime import date
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from storage import PrivateStore
from receipt.local_time import uk_today
from meals.ingredients import parse, number
from meals.nutrition_guidance import ages

FILE = Path(__file__).resolve().parents[1] / "data" / "meal_household.json"
ALLERGENS = (
    "cereals_containing_gluten",
    "crustaceans",
    "eggs",
    "fish",
    "peanuts",
    "soybeans",
    "milk",
    "nuts",
    "celery",
    "mustard",
    "sesame",
    "sulphites",
    "lupin",
    "molluscs",
)
TERMS = {
    "cereals_containing_gluten": r"\b(wheat|wholewheat|wholemeal|bread|toast|pasta|couscous|barley|rye|oats|cereals?|flour|tortillas?)\b",
    "milk": r"\b(milk|yoghurt|yogurt|butter|cheese|cheddar|feta|cream|halloumi|parmesan)\b",
    "eggs": r"\beggs?\b",
    "fish": r"\b(fish|salmon|cod|tuna|mackerel|sardines?|trout)\b",
    "peanuts": r"\bpeanuts?\b",
    "nuts": r"\b(nuts?|almonds?|walnuts?|cashews?|hazelnuts?|pecans?)\b",
    "soybeans": r"\b(soya|soy|tofu|edamame)\b",
    "sesame": r"\b(sesame|tahini)\b",
    "crustaceans": r"\b(prawns?|shrimp|crab|lobster)\b",
    "molluscs": r"\b(mussels?|oysters?|squid|clams?|scallops?)\b",
    "celery": r"\b(celery|celeriac)\b",
    "mustard": r"\bmustard\b",
    "lupin": r"\blupin\b",
    "sulphites": r"\b(sulphites|sulfites)\b",
}


def person():
    return dict(
        name="Person 1",
        birth_year=None,
        reference="range",
        diet="omnivore",
        allergens=[],
        avoid=[],
        clinical=False,
        notes="",
        portion=1.0,
    )


def defaults():
    return dict(
        version=1,
        configured=False,
        people=[person()],
        balanced=True,
        seasonal=True,
        dinners=None,
        breakfasts=None,
        breakfast_enabled=True,
        weekday_minutes=5,
        weekend_minutes=25,
        breakfast_start="07:00",
        breakfast_end="10:00",
        eating_minutes=15,
        provisional_weekends=False,
        breakfast_overrides={},
        breakfast_done=[],
        custom=[],
        reserve_days=3,
        water_litres=3.0,
        water_have=0.0,
        reserve_targets={},
        reserve_have={},
        reserve_notes="",
    )


def label(value, limit=160):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Use a short single-line label.")
    return value.strip()


def validate(s):
    from datetime import time

    if not isinstance(s, dict) or s.get("version") != 1:
        raise ValueError("Invalid household meal settings.")
    for key in (
        "configured",
        "balanced",
        "seasonal",
        "breakfast_enabled",
        "provisional_weekends",
    ):
        if type(s[key]) is not bool:
            raise ValueError("Invalid meal flag.")
    if not isinstance(s["people"], list) or not 1 <= len(s["people"]) <= 20:
        raise ValueError("Use 1–20 household profiles.")
    for p in s["people"]:
        label(p["name"], 80)
        if p["birth_year"] is not None and (
            type(p["birth_year"]) is not int
            or not uk_today().year - 120 <= p["birth_year"] <= uk_today().year
        ):
            raise ValueError("Check the birth year.")
        if p["reference"] not in ("male", "female", "range") or p["diet"] not in (
            "omnivore",
            "vegetarian",
            "vegan",
        ):
            raise ValueError("Invalid dietary profile.")
        if not isinstance(p["allergens"], list) or any(
            v not in ALLERGENS for v in p["allergens"]
        ):
            raise ValueError("Invalid allergen.")
        if not isinstance(p["avoid"], list) or len(p["avoid"]) > 30:
            raise ValueError("Too many food exclusions.")
        for v in p["avoid"]:
            label(v, 80)
        label(p["notes"], 300)
        if (
            type(p["clinical"]) is not bool
            or type(p["portion"]) not in (int, float)
            or not 0.25 <= p["portion"] <= 3
        ):
            raise ValueError("Use a portion factor from 0.25 to 3.")
    for key in ("dinners", "breakfasts"):
        if s[key] is not None and (
            not isinstance(s[key], list)
            or not 1 <= len(s[key]) <= 300
            or any(not isinstance(v, str) or len(v) > 160 for v in s[key])
        ):
            raise ValueError("Keep at least one enabled meal or use all.")
    for key, low, high in (
        ("weekday_minutes", 1, 15),
        ("weekend_minutes", 5, 90),
        ("eating_minutes", 5, 60),
        ("reserve_days", 1, 30),
    ):
        if type(s[key]) is not int or not low <= s[key] <= high:
            raise ValueError("Check the time/day limits.")
    if time.fromisoformat(s["breakfast_start"]) >= time.fromisoformat(
        s["breakfast_end"]
    ):
        raise ValueError("Breakfast must finish after it starts.")
    for key in ("water_litres", "water_have"):
        if type(s[key]) not in (int, float) or not 0 <= s[key] <= 10000:
            raise ValueError("Use a valid water quantity.")
    if not isinstance(s["custom"], list) or len(s["custom"]) > 30:
        raise ValueError("Use up to 30 custom recipes.")
    names = set()
    ids = set()
    for r in s["custom"]:
        if not re.fullmatch(r"[a-f0-9]{24}", r["id"]) or r["id"] in ids:
            raise ValueError("Invalid custom recipe identity.")
        ids.add(r["id"])
        label(r["name"], 120)
        if (
            not r["name"]
            or r["name"].casefold() in names
            or r["slot"] not in ("dinner", "breakfast")
        ):
            raise ValueError("Use unique recipe names and a meal type.")
        names.add(r["name"].casefold())
        if (
            type(r["total_minutes"]) is not int
            or not 1 <= r["total_minutes"] <= 240
            or type(r["cook_servings"]) not in (int, float)
            or not 0.25 <= r["cook_servings"] <= 30
        ):
            raise ValueError("Check recipe duration and yield.")
        if not isinstance(r.get("dietary"), dict) or any(
            type(r["dietary"].get(k)) is not bool for k in ("vegan", "vegetarian")
        ):
            raise ValueError("Invalid recipe diet flags.")
        kcal = r.get("nutrition_per_serving", {}).get("calories")
        if kcal is not None and (type(kcal) is not int or not 0 < kcal <= 3000):
            raise ValueError("Invalid energy estimate.")
        for key in ("ingredients", "method"):
            if not isinstance(r[key], list) or not 1 <= len(r[key]) <= 40:
                raise ValueError("Add ingredients and a method.")
            for v in r[key]:
                label(v, 300)
        if any(a not in ALLERGENS for a in r["allergens"]["uk_14"]):
            raise ValueError("Invalid recipe allergen.")
    for key in ("breakfast_overrides", "reserve_targets", "reserve_have"):
        if not isinstance(s[key], dict) or len(s[key]) > 400:
            raise ValueError("Too many saved meal choices.")
    if not isinstance(s["breakfast_done"], list) or len(s["breakfast_done"]) > 400:
        raise ValueError("Too much breakfast history.")
    for day in s["breakfast_done"]:
        date.fromisoformat(day)
    for day, name in s["breakfast_overrides"].items():
        date.fromisoformat(day)
        label(name, 160)
    for key in ("reserve_targets", "reserve_have"):
        for name, amount in s[key].items():
            label(name, 80)
            if type(amount) not in (int, float) or not 0 <= amount <= 10000:
                raise ValueError("Use non-negative reserve quantities.")
    label(s["reserve_notes"], 500)


def store():
    return PrivateStore(FILE, default=defaults, validate=validate, max_bytes=350000)


def signature(s):
    return hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()[:16]


def shared(s, on):
    return [p for p in s["people"] if not ages(p, on) or ages(p, on)[0] >= 2]


def inferred(recipe):
    text = " ".join(recipe.get("ingredients", [])).casefold()
    result = set()
    for allergen, pattern in TERMS.items():
        remaining = text
        if allergen == "cereals_containing_gluten":
            remaining = re.sub(
                r"certified gluten-free oats|gluten-free (?:bread|toast|pasta|cereal|flour)",
                "",
                remaining,
            )
        if allergen == "milk":
            remaining = re.sub(
                r"(?:soya|soy|oat|almond|coconut) (?:milk|yoghurt|yogurt|cream)",
                "",
                remaining,
            )
        if re.search(pattern, remaining):
            result.add(allergen)
    return result


def recipe_signature(recipe):
    keys = (
        "id",
        "slot",
        "name",
        "ingredients",
        "method",
        "total_minutes",
        "cook_servings",
        "dietary",
        "allergens",
        "nutrition_per_serving",
    )
    return hashlib.sha256(
        json.dumps({k: recipe.get(k) for k in keys}, sort_keys=True).encode()
    ).hexdigest()


def permitted(recipe, s, on, slot="dinner"):
    if recipe.get("id") and recipe.get("slot") in ("dinner", "breakfast"):
        current = next(
            (r for r in s["custom"] if r["id"] == recipe["id"] and r["slot"] == slot),
            None,
        )
        if current is None or recipe.get(
            "_household_recipe_signature", recipe_signature(recipe)
        ) != recipe_signature(current):
            return False
    if not s["configured"]:
        return True
    if not shared(s, on):
        return False
    allowed = s["dinners" if slot == "dinner" else "breakfasts"]
    if allowed is not None and recipe["name"] not in allowed:
        return False
    a = recipe.get("allergens", {})
    declared = set(a.get("uk_14", []) if isinstance(a, dict) else a)
    allergens = declared | inferred(recipe)
    text = (
        recipe.get("name", "") + " " + " ".join(recipe.get("ingredients", []))
    ).casefold()
    for p in s["people"]:
        if set(p["allergens"]) & allergens:
            return False
        diet = recipe.get("dietary", {})
        animal = bool(
            re.search(
                r"\b(chicken|beef|lamb|pork|turkey|duck|fish|salmon|cod|tuna|prawns?|ham|bacon)\b",
                text,
            )
        )
        if p["diet"] in ("vegetarian", "vegan") and animal:
            return False
        if p["diet"] == "vegan" and {"milk", "eggs"} & allergens:
            return False
        if p["diet"] == "vegan" and not diet.get("vegan", False):
            return False
        if p["diet"] == "vegetarian" and not diet.get("vegetarian", False):
            return False
        if any(term.casefold() in text for term in p["avoid"] if term.strip()):
            return False
        span = ages(p, on)
        if (
            span
            and span[0] < 5
            and re.search(
                r"\b(whole (?:nuts|peanuts)|almonds|walnuts|cashews|hazelnuts|granola)\b",
                text,
            )
        ):
            return False
    return True


def scaled_line(line, factor):
    r = parse(line)
    if not r:
        return (
            line
            if factor == 1
            else line + f" (unmeasured; scale for {float(factor):g}x)"
        )
    amount, unit, _, name = r
    amount *= factor
    if unit == "tsp" and amount >= 3 and amount % 3 == 0:
        amount /= 3
        unit = "tbsp"
    return (
        f"{number(amount)}"
        + (
            f"{unit} "
            if unit in ("g", "ml")
            else f" {unit} "
            if unit != "count"
            else " "
        )
        + name
    )


def prepare(recipe, on, s=None):
    s = s or store().read()
    if not s["configured"] or recipe.get("_household_scaled"):
        return deepcopy(recipe)
    result = deepcopy(recipe)
    people = shared(s, on)
    if not people:
        raise ValueError(
            "No shared-meal diners: under-twos need a separate feeding plan."
        )
    portions = sum(p["portion"] for p in people)
    base = float(recipe.get("cook_servings", recipe.get("servings", 1)) or 1)
    # Keep at least the original batch yield; planned batch surplus is displayed, not silently eaten.
    from meals import legacy_planner
    from receipt.lifestyle import skip_meal
    from datetime import timedelta

    tomorrow = on + timedelta(days=1)
    lunch_override = legacy_planner._override_for(tomorrow, "lunch")
    reserve_lunch = not skip_meal(tomorrow) and not (
        lunch_override and lunch_override.get("type") in ("buy_lunch", "eat_out")
    )
    lunch_recipe = recipe.get("lunch", {}) if reserve_lunch else {}
    extra = (
        (
            1
            if lunch_recipe.get("source") == "batch_portion"
            else float(lunch_recipe.get("extra_dinner_portion", 0) or 0)
        )
        if lunch_recipe
        else 0
    )
    required = portions * (1 + max(0, extra))
    desired = (
        max(required, base)
        if recipe.get("meal_type") in ("batch", "whole_joint")
        else required
    )
    factor = Fraction(str(desired)) / Fraction(str(base))
    result["ingredients"] = [
        scaled_line(v, factor) for v in recipe.get("ingredients", [])
    ]
    if any((span := ages(p, on)) and span[0] < 5 for p in people):
        result["method"] = result.get("method", []) + [
            "For young children, adapt food size, shape and texture using NHS safe-food preparation guidance; supervise eating."
        ]
    for ref in result.get("prep_components", []):
        if isinstance(ref, dict) and type(ref.get("quantity")) in (int, float):
            ref["quantity"] *= float(factor)
    if not reserve_lunch:
        result["lunch"] = {}
    lunch = result.get("lunch")
    if lunch:
        lunch["extra_ingredients"] = [
            scaled_line(v, Fraction(str(portions)))
            for v in lunch.get("extra_ingredients", [])
        ]
    result.update(
        _household_scaled=True,
        _household_recipe_signature=recipe_signature(recipe),
        _household_diners=len(people),
        _household_portions=portions,
        _household_cook=desired,
        _household_signature=signature(s),
        _household_factor=float(factor),
        _household_lunch_reserved=bool(lunch_recipe),
    )
    return result


def meal(row, s=None):
    s = s or store().read()
    if row.get("kind") != "recipe":
        return deepcopy(row)
    on = date.fromisoformat(row["date"])
    if (s["configured"] and not shared(s, on)) or not permitted(row["recipe"], s, on):
        return dict(
            date=row["date"],
            kind="needs_review",
            name="Meal needs review: " + row["recipe"]["name"],
            overview="Update the menu using your household settings before shopping or cooking.",
            _needs_review=True,
        )
    return dict(row, recipe=prepare(row["recipe"], on, s))


def plan(value, s=None):
    s = s or store().read()
    result = deepcopy(value)
    result["meals"] = [meal(row, s) for row in result.get("meals", [])]
    return result


def compatible_existing(value, on, prefs):
    from meals import legacy_planner
    from web_control.live_data import meal_confirmation

    return dict(
        value,
        meals=[
            row
            for row in value.get("meals", [])
            if row.get("kind") != "recipe"
            or date.fromisoformat(row["date"]) < on
            or meal_confirmation(date.fromisoformat(row["date"]))
            or legacy_planner._eligible(
                row["recipe"], date.fromisoformat(row["date"]), prefs
            )
        ],
    )
