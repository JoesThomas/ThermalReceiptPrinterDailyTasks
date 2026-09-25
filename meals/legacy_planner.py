"""Meal planning subsystem for the thermal daily information receipt.

No third-party dependencies. Data lives in JSON files beside this module by default.
The planner is intentionally conservative about allergens/storage: metadata is guidance,
not a substitute for package labels or food-safety advice.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from data_store import edit_json, read_json, write_json

TZ = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parent
BASE_DIR = ROOT.parent
DATA_DIR = BASE_DIR / "data"
RECIPES_FILE = DATA_DIR / "recipes.json"
COMPONENTS_FILE = DATA_DIR / "components.json"
COOKING_RULES_FILE = DATA_DIR / "cooking_rules.json"
EQUIPMENT_FILE = DATA_DIR / "equipment.json"
PREFERENCES_FILE = DATA_DIR / "meal_preferences.json"
PANTRY_FILE = DATA_DIR / "pantry.json"
FREEZER_FILE = DATA_DIR / "freezer.json"
HISTORY_FILE = DATA_DIR / "recipe_history.json"
OVERRIDES_FILE = DATA_DIR / "meal_overrides.json"
PLANS_DIR = BASE_DIR / "meal_plans"
RECEIPT_WIDTH = 42


def _load(path: Path, default: Any) -> Any:
    return read_json(
        path,
        default,
    )


def _save(path: Path, data: Any) -> None:
    write_json(
        path,
        data,
    )


def recipes() -> list[dict]:
    data = _load(RECIPES_FILE, [])
    if isinstance(data, dict):
        return data.get("recipes", [])
    return data if isinstance(data, list) else []


def preferences() -> dict:
    return _load(PREFERENCES_FILE, {})


def sunday_for(day: date) -> date:
    return day + timedelta(days=(6 - day.weekday()) % 7)


def current_week_sunday(day: date) -> date:
    # Sunday-start week. On Sunday, returns today; otherwise previous Sunday.
    return day - timedelta(days=(day.weekday() + 1) % 7)


def plan_path(start: date) -> Path:
    return PLANS_DIR / f"{start.isoformat()}.json"


def load_plan_for(day: date) -> dict | None:
    plan = _load(plan_path(current_week_sunday(day)), None)
    return plan if isinstance(plan, dict) else None


def _allergens(recipe: dict) -> set[str]:
    value = recipe.get("allergens", {})
    if isinstance(value, dict):
        return set(value.get("uk_14", []))
    if isinstance(value, list):
        return set(value)
    return set()


def _primary(recipe: dict) -> str:
    return str(recipe.get("balance", {}).get("protein", "") or "")


def _carb(recipe: dict) -> str:
    return str(recipe.get("balance", {}).get("carbohydrate", "") or "")


def _eligible(recipe: dict, meal_day: date, prefs: dict) -> bool:
    excluded = set(prefs.get("excluded_allergens", []))
    if excluded & _allergens(recipe):
        return False
    if meal_day.weekday() < 5 and int(recipe.get("total_minutes", 999)) > int(prefs.get("weekday_max_minutes", 30)):
        return False
    dietary = recipe.get("dietary", {})
    if prefs.get("vegetarian_only") and not dietary.get("vegetarian", False):
        return False
    if prefs.get("vegan_only") and not dietary.get("vegan", False):
        return False
    return True


def _history_penalty(recipe: dict, history: dict, today: date) -> float:
    item = history.get(recipe.get("name", ""), {})
    last = item.get("last_cooked")
    if not last:
        return 0.0
    try:
        age = (today - date.fromisoformat(last)).days
    except ValueError:
        return 0.0
    if age < 14:
        return 10.0
    if age < 35:
        return 4.0
    return min(float(item.get("times_cooked", 0)) * 0.15, 2.0)


def _score(recipe: dict, previous: dict | None, used: set[str], history: dict, day: date, want_batch: bool) -> float:
    if recipe.get("name") in used:
        return -1000.0
    score = random.random() * 4.0
    score -= _history_penalty(recipe, history, day)
    if previous:
        if _primary(recipe) and _primary(recipe) == _primary(previous):
            score -= 8
        if _carb(recipe) and _carb(recipe) == _carb(previous):
            score -= 2
        if recipe.get("cuisine") == previous.get("cuisine"):
            score -= 3
    mt = recipe.get("meal_type", "single")
    if want_batch and mt in {"batch", "whole_joint"}:
        score += 12
    elif mt in {"batch", "whole_joint"}:
        score -= 2
    effort = recipe.get("effort", "medium")
    if day.weekday() < 4 and effort == "high":
        score -= 4
    return score


def _override_for(day: date, scope: str = "dinner") -> dict | None:
    data = _load(OVERRIDES_FILE, {})
    item = data.get(day.isoformat()) if isinstance(data, dict) else None
    if not isinstance(item, dict):
        return None
    if "type" in item:  # backwards-compatible dinner override
        return item if scope == "dinner" else None
    scoped = item.get(scope)
    return scoped if isinstance(scoped, dict) else None


def _special_meal(day: date, override: dict) -> dict:
    kind = override.get("type", "takeaway")
    labels = {
        "takeaway": "TAKEAWAY",
        "eat_out": "EAT OUT",
        "buy_lunch": "BUY LUNCH",
        "freezer": "FREEZER MEAL",
        "treat": "TREAT MEAL",
    }
    return {
        "date": day.isoformat(), "kind": kind,
        "name": override.get("name") or labels.get(kind, kind.upper()),
        "overview": override.get("note", "Planned non-recipe meal."),
        "estimated_cost": float(override.get("estimated_cost", 0) or 0),
    }


def generate_week(start: date | None = None, force: bool = False) -> dict:
    today = datetime.now(TZ).date()
    start = start or sunday_for(today)
    path = plan_path(start)
    if path.exists() and not force:
        return _load(path, {})

    prefs = preferences()
    library = recipes()
    history = _load(HISTORY_FILE, {})
    if not library:
        raise RuntimeError("recipes.json contains no recipes")

    meals, used = [], set()
    previous = None
    batch_used = False
    preferred_batch_day = int(prefs.get("batch_preferred_weekday", 6))  # Sunday=6

    for offset in range(7):
        d = start + timedelta(days=offset)
        override = _override_for(d)
        if override and override.get("type") in {"takeaway", "eat_out", "freezer", "treat"}:
            meals.append(_special_meal(d, override))
            previous = None
            continue

        pool = [r for r in library if _eligible(r, d, prefs)]
        if not pool:
            raise RuntimeError(f"No eligible recipes for {d.isoformat()}; check allergen/diet settings")
        want_batch = (not batch_used and d.weekday() == preferred_batch_day)
        ranked = sorted(pool, key=lambda r: _score(r, previous, used, history, d, want_batch), reverse=True)
        chosen = ranked[0]
        used.add(chosen.get("name", ""))
        if chosen.get("meal_type") in {"batch", "whole_joint"}:
            batch_used = True
        meals.append({"date": d.isoformat(), "kind": "recipe", "recipe": chosen})
        previous = chosen

    plan = {
        "generated": today.isoformat(),
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=6)).isoformat(),
        "meals": meals,
    }
    plan["prep"] = build_sunday_prep(plan)
    plan["shopping"] = build_shopping_list(plan)
    plan["estimated_cost"] = estimate_week_cost(plan)
    _save(path, plan)
    return plan


def get_meal(day: date | None = None) -> dict | None:
    day = day or datetime.now(TZ).date()
    plan = load_plan_for(day)
    if not plan:
        plan = generate_week(current_week_sunday(day))
    return next((m for m in plan.get("meals", []) if m.get("date") == day.isoformat()), None)


def _normalise_item(text: str) -> str:
    text = re.sub(r"^\s*\d+(?:\.\d+)?\s*(?:g|kg|ml|l|tsp|tbsp|x)?\s*", "", text.lower())
    text = re.sub(r"^\s*\d+\s*/\s*\d+\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _pantry_has(ingredient: str) -> bool:
    pantry = _load(PANTRY_FILE, {})
    items = pantry.get("items", {}) if isinstance(pantry, dict) else {}
    needle = _normalise_item(ingredient)
    for key, value in items.items():
        if value and (_normalise_item(key) in needle or needle in _normalise_item(key)):
            return True
    return False


def _section(ingredient: str) -> str:
    s = ingredient.lower()
    if any(x in s for x in ["chicken", "beef", "pork", "lamb", "turkey", "salmon", "fish", "prawn", "tuna", "sausage"]): return "MEAT / FISH"
    if any(x in s for x in ["yoghurt", "milk", "cheddar", "parmesan", "feta", "halloumi", "mozzarella", "ricotta", "paneer", "egg"]): return "DAIRY / EGGS"
    if any(x in s for x in ["bread", "roll", "pitta", "flatbread", "tortilla"]): return "BAKERY"
    if any(x in s for x in ["pepper", "onion", "carrot", "broccoli", "spinach", "lettuce", "tomato", "lemon", "lime", "garlic", "ginger", "aubergine", "potato", "cabbage", "salad", "herb", "courgette", "peas", "greens"]): return "FRUIT / VEG"
    return "TINNED / DRY"


def build_shopping_list(plan: dict) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    seen = set()
    for meal in plan.get("meals", []):
        if meal.get("kind") != "recipe":
            continue
        r = meal["recipe"]
        for item in r.get("ingredients", []):
            key = _normalise_item(item)
            if key and key not in seen and not _pantry_has(item):
                grouped[_section(item)].append(item)
                seen.add(key)
        meal_day = date.fromisoformat(meal["date"])
        next_day = meal_day + timedelta(days=1)
        lunch_override = _override_for(next_day, "lunch")
        lunch = {} if lunch_override and lunch_override.get("type") in {"buy_lunch", "eat_out"} else r.get("lunch", {})
        for item in lunch.get("extra_ingredients", []):
            key = _normalise_item(item)
            if key and key not in seen and not _pantry_has(item):
                grouped[_section(item)].append(item)
                seen.add(key)
    return dict(grouped)


def build_sunday_prep(plan: dict) -> list[dict]:
    components = _load(COMPONENTS_FILE, {}).get("components", [])
    by_id = {c.get("id"): c for c in components}
    needs: dict[str, list[str]] = defaultdict(list)
    for meal in plan.get("meals", []):
        if meal.get("kind") != "recipe":
            continue
        r = meal["recipe"]
        for ref in r.get("prep_components", []):
            cid = ref.get("id") if isinstance(ref, dict) else ref
            if cid:
                needs[cid].append(date.fromisoformat(meal["date"]).strftime("%a").upper())

    prefs = preferences()
    mode = prefs.get("prep_preference", "smart")
    result = []
    for cid, days in needs.items():
        c = by_id.get(cid)
        if not c:
            continue
        choice = c.get("default_action", "buy")
        override = prefs.get("component_preferences", {}).get(cid)
        if override in {"buy", "make"}:
            choice = override
        elif mode == "buy":
            choice = "buy"
        elif mode == "make" and c.get("make"):
            choice = "make"
        elif mode == "smart":
            # Make if used repeatedly and quick to prepare; otherwise use component default.
            if len(days) >= 2 and c.get("make") and int(c["make"].get("minutes", 99)) <= 15:
                choice = "make"
        result.append({"id": cid, "name": c.get("name", cid), "action": choice, "used": days, "details": c.get(choice, {})})
    return result


def estimate_week_cost(plan: dict) -> dict:
    recipe_cost = 0.0
    extras = 0.0
    for meal in plan.get("meals", []):
        if meal.get("kind") == "recipe":
            recipe_cost += float(meal["recipe"].get("cost", {}).get("estimated_per_portion", 0) or 0)
        else:
            extras += float(meal.get("estimated_cost", 0) or 0)
    return {"home_meals": round(recipe_cost, 2), "takeaway_eating_out": round(extras, 2), "total": round(recipe_cost + extras, 2)}


def record_cooked(
    recipe_name: str,
    when: date | None = None,
) -> None:
    when = (
        when
        or datetime.now(TZ).date()
    )

    with edit_json(
        HISTORY_FILE,
        {},
    ) as history:
        item = history.setdefault(
            recipe_name,
            {
                "times_cooked": 0,
            },
        )

        item["times_cooked"] = (
            int(
                item.get(
                    "times_cooked",
                    0,
                )
            )
            + 1
        )

        item[
            "last_cooked"
        ] = when.isoformat()


def add_freezer_portions(
    name: str,
    portions: int,
    source: str = "batch cook",
) -> None:
    with edit_json(
        FREEZER_FILE,
        {
            "items": [],
        },
    ) as data:
        items = data.setdefault(
            "items",
            [],
        )

        existing = next(
            (
                item
                for item in items
                if str(
                    item.get(
                        "name",
                        "",
                    )
                ).lower()
                == name.lower()
            ),
            None,
        )

        if existing:
            existing["portions"] = (
                int(
                    existing.get(
                        "portions",
                        0,
                    )
                )
                + portions
            )
        else:
            items.append({
                "name": name,
                "portions": portions,
                "source": source,
                "added": datetime.now(
                    TZ
                ).date().isoformat(),
            })


def use_freezer_portion(
    name: str,
) -> bool:
    used = False

    with edit_json(
        FREEZER_FILE,
        {
            "items": [],
        },
    ) as data:
        for item in data.get(
            "items",
            [],
        ):
            if (
                str(
                    item.get(
                        "name",
                        "",
                    )
                ).lower()
                == name.lower()
                and int(
                    item.get(
                        "portions",
                        0,
                    )
                )
                > 0
            ):
                item["portions"] -= 1
                used = True
                break

    return used


def set_override(day: date, meal_type: str, name: str = "", estimated_cost: float = 0.0, note: str = "", scope: str = "dinner") -> None:
    data = _load(OVERRIDES_FILE, {})
    day_item = data.setdefault(day.isoformat(), {})
    if "type" in day_item:
        day_item = {"dinner": day_item}
        data[day.isoformat()] = day_item
    day_item[scope] = {"type": meal_type, "name": name, "estimated_cost": estimated_cost, "note": note}
    _save(OVERRIDES_FILE, data)


def clear_override(day: date, scope: str | None = None) -> None:
    data = _load(OVERRIDES_FILE, {})
    if scope and isinstance(data.get(day.isoformat()), dict) and "type" not in data[day.isoformat()]:
        data[day.isoformat()].pop(scope, None)
        if not data[day.isoformat()]:
            data.pop(day.isoformat(), None)
    else:
        data.pop(day.isoformat(), None)
    _save(OVERRIDES_FILE, data)


def wrap(text: str, width: int = RECEIPT_WIDTH) -> list[str]:
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        trial = word if not current else current + " " + word
        if len(trial) <= width:
            current = trial
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    return lines or [""]



def _equipment() -> dict:
    return _load(EQUIPMENT_FILE, {})


def _cooking_rules() -> dict:
    return _load(COOKING_RULES_FILE, {})


def _extract_grams(ingredient: str) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*g\b", ingredient.lower())
    return int(round(float(match.group(1)))) if match else None


def _matching_cooking_rule(ingredient: str):
    text = ingredient.lower()
    aliases = {
        "basmati_rice": ("basmati rice",),
        "jasmine_rice": ("jasmine rice",),
        "couscous": ("couscous",),
        "quinoa": ("quinoa",),
        "bulgur_wheat": ("bulgur",),
        "polenta": ("polenta",),
        "porridge_oats": ("porridge oats", "rolled oats"),
        "pasta": ("pasta", "spaghetti", "tagliatelle", "penne", "rigatoni", "fusilli", "orzo"),
    }
    for rule_id, names in aliases.items():
        if any(name in text for name in names):
            return rule_id, _cooking_rules().get(rule_id, {})
    return None, None


def cooking_hint_for_recipe(recipe: dict) -> list[str]:
    """Return compact, equipment-aware cooking hints for ratio staples."""
    hints = []
    equipment = _equipment()
    rice_cooker = equipment.get("rice_cooker", {})
    if isinstance(rice_cooker, bool):
        rice_cooker = {"owned": rice_cooker}

    for ingredient in recipe.get("ingredients", []):
        rule_id, rule = _matching_cooking_rule(ingredient)
        if not rule:
            continue

        grams = _extract_grams(ingredient)
        if not grams:
            continue

        # Rice cooker only when the amount reaches its configured minimum.
        if rule_id in {"basmati_rice", "jasmine_rice"}:
            portion_g = int(rule.get("portion_g", 75))
            portions = grams / portion_g
            minimum = int(rice_cooker.get("minimum_portions", 2) or 2)
            if rice_cooker.get("owned") and portions >= minimum:
                hints.append(
                    f"{rule.get('display_name','Rice').upper()}: {grams}g - use rice cooker "
                    f"({portions:g} portions; minimum {minimum})."
                )
            else:
                saucepan = rule.get("saucepan", {})
                water_per = saucepan.get("water_ml_per_75g")
                water = round((grams / portion_g) * water_per) if water_per else None
                if water:
                    hints.append(
                        f"{rule.get('display_name','Rice').upper()}: {grams}g / ~{water}ml water. "
                        + " ".join(saucepan.get("instructions", []))
                    )
            continue

        if rule.get("rule_type") == "non_ratio":
            hints.append(
                f"{rule.get('display_name','COOKING').upper()}: "
                + " ".join(rule.get("instructions", []))
            )
            continue

        portion_g = int(rule.get("portion_g", 75))
        liquid_key = next((k for k in rule if k.startswith("liquid_ml_per_")), None)
        if liquid_key:
            base_g = int(re.search(r"(\d+)g", liquid_key).group(1))
            liquid = round((grams / base_g) * float(rule[liquid_key]))
            hints.append(
                f"{rule.get('display_name','COOKING').upper()}: {grams}g / ~{liquid}ml "
                f"{rule.get('liquid','liquid')}. " + " ".join(rule.get("instructions", []))
            )
    return hints


def _prep_order(prep: list[dict]) -> list[str]:
    """Create a practical prep order: long background jobs first, quick jobs while they run."""
    make_items = [x for x in prep if x.get("action") == "make"]
    if not make_items:
        return []

    def background(item):
        return int(item.get("details", {}).get("background_minutes", 0) or 0)

    long_jobs = sorted([x for x in make_items if background(x) >= 20], key=background, reverse=True)
    quick_jobs = sorted([x for x in make_items if background(x) < 20],
                        key=lambda x: int(x.get("details", {}).get("minutes", 0) or 0))

    order = []
    for item in long_jobs:
        order.append(f"Start {item['name'].lower()} so its background time can run.")
    for item in quick_jobs:
        order.append(f"Make {item['name'].lower()} while longer jobs are proving, roasting or simmering.")
    return order


def _print_wrapped_step(printer, left, number: int, text: str) -> None:
    pieces = wrap(text, RECEIPT_WIDTH - 3)
    for j, piece in enumerate(pieces):
        left(printer, (f"{number}. " if j == 0 else "   ") + piece)


def print_weekly_overview(printer, left, line) -> None:
    today = datetime.now(TZ).date()
    plan = generate_week(sunday_for(today))
    line(printer, "="); left(printer, "MEALS FOR THE WEEK"); line(printer, "=")
    for meal in plan.get("meals", []):
        d = date.fromisoformat(meal["date"])
        if meal.get("kind") == "recipe":
            r = meal["recipe"]
            left(printer, f"{d.strftime('%a').upper()} {r['name'].upper()}"[:RECEIPT_WIDTH])
            for x in wrap(r.get("overview", ""), RECEIPT_WIDTH): left(printer, "  " + x[:RECEIPT_WIDTH-2])
            n = r.get("nutrition_per_serving", {})
            left(printer, f"  {r.get('total_minutes',0)}M / ~{n.get('calories','?')} KCAL / {n.get('protein_g','?')}G P")
        else:
            left(printer, f"{d.strftime('%a').upper()} {meal.get('name','').upper()}"[:RECEIPT_WIDTH])
    cost = plan.get("estimated_cost", {})
    if cost.get("total"):
        line(printer, "-"); left(printer, f"EST. PLANNED FOOD: £{cost['total']:.2f}")


def print_sunday_prep(printer, left, line) -> None:
    today = datetime.now(TZ).date()
    if today.weekday() != 6:
        return

    plan = load_plan_for(today) or generate_week(today)
    prep = plan.get("prep", [])

    line(printer, "=")
    left(printer, "SUNDAY KITCHEN PLAN")
    line(printer, "=")

    if not prep:
        left(printer, "NO PREP NEEDED")
        return

    make_items = [x for x in prep if x.get("action") == "make"]
    buy_items = [x for x in prep if x.get("action") == "buy"]

    active = sum(int(x.get("details", {}).get("minutes", 0) or 0) for x in make_items)
    background = max(
        [int(x.get("details", {}).get("background_minutes", 0) or 0) for x in make_items] or [0]
    )

    left(printer, f"ACTIVE TIME: ~{active} MIN")
    if background:
        left(printer, f"BACKGROUND: ~{background} MIN")

    line(printer, "-")
    left(printer, "MAKE")
    for item in make_items:
        yield_text = item.get("details", {}).get("yield", "")
        suffix = f" - {yield_text}" if yield_text else ""
        left(printer, f"{item['name'].upper()}{suffix}"[:RECEIPT_WIDTH])
        if item.get("used"):
            left(printer, "  USED: " + " / ".join(item["used"]))

    if buy_items:
        line(printer, "-")
        left(printer, "BUY / USE BOUGHT")
        for item in buy_items:
            left(printer, item["name"].upper())

    order = _prep_order(prep)
    if order:
        line(printer, "=")
        left(printer, "PREP ORDER")
        line(printer, "-")
        for i, step in enumerate(order, 1):
            _print_wrapped_step(printer, left, i, step)

    if make_items:
        line(printer, "=")
        left(printer, "SUNDAY PREP RECIPES")
        line(printer, "=")

    for item in make_items:
        details = item.get("details", {})
        left(printer, item["name"].upper())
        line(printer, "-")

        for ingredient in details.get("ingredients", []):
            left(printer, "- " + ingredient)

        if details.get("yield"):
            left(printer, "MAKES: " + str(details["yield"]).upper())

        line(printer, "-")
        for i, step in enumerate(details.get("method", []), 1):
            _print_wrapped_step(printer, left, i, step)

        storage = details.get("storage")
        if storage:
            left(printer, "STORE:")
            for x in wrap(storage, RECEIPT_WIDTH - 2):
                left(printer, "  " + x)

        allergens = details.get("allergens", [])
        if allergens:
            left(printer, "ALLERGENS: " + ", ".join(allergens).upper())

        check = details.get("check_labels_for", [])
        if check:
            left(printer, "CHECK LABELS: " + ", ".join(check).upper())

        if item.get("used"):
            left(printer, "USED: " + " / ".join(item["used"]))

        line(printer, "-")



def print_today_recipe(printer, left, line) -> None:
    today = datetime.now(TZ).date()
    meal = get_meal(today)
    if not meal:
        return
    line(printer, "="); left(printer, "TODAY'S RECIPE");
    line(printer, "-")
    if meal.get("kind") != "recipe":
        left(printer, meal.get("name", "PLANNED MEAL").upper())
        for x in wrap(meal.get("overview", "")): left(printer, x)
        return
    r = meal["recipe"]
    left(printer, r.get("name", "RECIPE").upper())
    left(printer, f"{r.get('total_minutes',0)} MIN / SERVES 1 / {r.get('effort','MEDIUM').upper()} EFFORT")
    for x in wrap(r.get("overview", "")): left(printer, x)
    n = r.get("nutrition_per_serving", {})
    left(printer, f"~{n.get('calories','?')} KCAL  P {n.get('protein_g','?')}G  C {n.get('carbs_g','?')}G")
    left(printer, f"FAT {n.get('fat_g','?')}G  FIBRE {n.get('fibre_g','?')}G")
    allergens = sorted(_allergens(r))
    left(printer, "ALLERGENS: " + (", ".join(a.replace("cereals_containing_gluten","gluten") for a in allergens).upper() if allergens else "NONE LISTED"))
    if r.get("allergens", {}).get("check_labels_for"):
        left(printer, "CHECK LABELS: " + ", ".join(r["allergens"]["check_labels_for"]).upper())
    line(printer, "-"); left(printer, "INGREDIENTS")
    for item in r.get("ingredients", []): left(printer, "- " + item)
    line(printer, "-"); left(printer, "METHOD")
    for i, step in enumerate(r.get("method", []), 1):
        for j, x in enumerate(wrap(step, RECEIPT_WIDTH-3)):
            left(printer, (f"{i}. " if j == 0 else "   ") + x)
    cooking_hints = cooking_hint_for_recipe(r)
    if cooking_hints:
        line(printer, "-")
        left(printer, "COOKING GUIDE")
        for hint in cooking_hints:
            for x in wrap(hint, RECEIPT_WIDTH - 2):
                left(printer, "- " + x)

    if r.get("hacks"):
        line(printer, "-"); left(printer, "COOKING TIPS")
        for tip in r["hacks"][:2]:
            for x in wrap(tip, RECEIPT_WIDTH-2): left(printer, "- " + x if x == wrap(tip, RECEIPT_WIDTH-2)[0] else "  " + x)
    tomorrow = today + timedelta(days=1)
    lunch_override = _override_for(tomorrow, "lunch")
    lunch = r.get("lunch", {})
    if lunch_override and lunch_override.get("type") in {"buy_lunch", "eat_out"}:
        lunch = {"name": lunch_override.get("name") or ("BUY LUNCH" if lunch_override.get("type") == "buy_lunch" else "EAT OUT"), "overview": lunch_override.get("note", "No lunch ingredients needed."), "extra_ingredients": []}
    if lunch:
        line(printer, "-"); left(printer, "LUNCH TOMORROW"); left(printer, lunch.get("name", "").upper())
        for x in wrap(lunch.get("overview", "")): left(printer, x)
        for item in lunch.get("extra_ingredients", []): left(printer, "+ " + item)


def print_shopping_list(printer, left, line, plan: dict | None = None) -> None:
    today = datetime.now(TZ).date()
    plan = plan or load_plan_for(today) or generate_week(sunday_for(today))
    line(printer, "="); left(printer, "MEAL SHOPPING LIST"); line(printer, "=")
    for section, items in plan.get("shopping", {}).items():
        left(printer, section)
        for item in items: left(printer, "[ ] " + item)
