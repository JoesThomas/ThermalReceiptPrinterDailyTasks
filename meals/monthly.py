"""Calendar-month menus backed by the existing weekly plans and dated shopping stops."""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import calendar
import re

from storage import PrivateStore, file_lock
from receipt.local_time import uk_today
from meals import legacy_planner as planner
from meals.ingredients import parse, aggregate

FILE = Path(__file__).resolve().parents[1] / "data" / "monthly_meals.json"
CATEGORIES = (
    "Store cupboard / frozen",
    "Meat",
    "Fish",
    "Fresh produce",
    "Fresh essentials",
)
SHOPS = (
    "Main supermarket shop",
    "Butcher",
    "Greengrocer",
    "Fishmonger",
    "Supermarket top-up",
    "Local shop",
)


def defaults():
    return dict(
        version=1,
        active_month="",
        weekly_day=5,
        veg_topup=False,
        veg_day=2,
        shops=dict(zip(CATEGORIES, (SHOPS[0], SHOPS[1], SHOPS[4], SHOPS[2], SHOPS[4]))),
        overrides={},
    )


def bounds(raw):
    if not re.fullmatch(r"\d{4}-\d{2}", str(raw)):
        raise ValueError("Choose a calendar month.")
    first = date.fromisoformat(raw + "-01")
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def validate(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Invalid monthly meal settings.")
    if value["active_month"]:
        bounds(value["active_month"])
    for field in ("weekly_day", "veg_day"):
        if type(value[field]) is not int or not 0 <= value[field] <= 6:
            raise ValueError("Choose a shopping weekday.")
    if type(value["veg_topup"]) is not bool:
        raise ValueError("Invalid top-up setting.")
    if not isinstance(value["shops"], dict) or set(value["shops"]) != set(CATEGORIES):
        raise ValueError("Invalid shop categories.")
    for category, shop in value["shops"].items():
        if shop not in SHOPS or (category != CATEGORIES[0] and shop == SHOPS[0]):
            raise ValueError(
                "Fresh food belongs in a weekly list, not the monthly main shop."
            )
    if not isinstance(value["overrides"], dict) or len(value["overrides"]) > 500:
        raise ValueError("Too many ingredient choices.")
    for name, category in value["overrides"].items():
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 200
            or any(ord(c) < 32 for c in name)
            or category not in CATEGORIES
        ):
            raise ValueError("Invalid ingredient choice.")


def store():
    return PrivateStore(FILE, default=defaults, validate=validate, max_bytes=150000)


def preferences():
    def valid(value):
        if not isinstance(value, dict):
            raise ValueError("Invalid meal preferences.")
        excluded = value.get("excluded_allergens", [])
        if (
            not isinstance(excluded, list)
            or len(excluded) > 30
            or any(not isinstance(v, str) or not v.strip() for v in excluded)
        ):
            raise ValueError("Invalid allergen preferences.")
        if any(
            type(value.get(flag, False)) is not bool
            for flag in ("vegetarian_only", "vegan_only")
        ):
            raise ValueError("Invalid dietary preferences.")
        if not isinstance(
            value.get("component_preferences", {}), dict
        ) or not isinstance(value.get("cooking_style", {}), dict):
            raise ValueError("Invalid cooking preferences.")

    return PrivateStore(
        planner.PREFERENCES_FILE, default=dict, validate=valid, max_bytes=150000
    ).read()


def identity(line):
    row = parse(line)
    return (
        (("tinned " if row[1] == "tin" else "") + row[2])
        if row
        else " ".join(str(line).casefold().split())
    )


def category(line):
    name = identity(line)
    # Explicit preservation and dry seasoning take precedence over fresh-food names.
    if re.search(
        r"\b(tin|tinned|canned|frozen|dried|powder|granules|spice|spices|salt|oil|vinegar|rice|couscous|flour|sugar|honey|passata|purée|puree|oats|lentils)\b",
        name,
    ):
        return CATEGORIES[0]
    if re.search(
        r"\b(cumin|paprika|turmeric|cinnamon|cayenne|chilli flakes|black pepper|white pepper)\b",
        name,
    ):
        return CATEGORIES[0]
    if re.search(r"\b(pasta|noodles)\b", name) and "fresh" not in name:
        return CATEGORIES[0]
    if re.search(r"\b(stock|broth)\b", name):
        return (
            CATEGORIES[0]
            if re.search(r"\b(cube|cubes|powder|concentrate)\b", name)
            else CATEGORIES[4]
        )
    if re.search(
        r"\b(paste|sauce|mayo|mayonnaise|pesto|yoghurt|yogurt|milk|cheese|egg|eggs|butter|cream|ham|bacon|salami|chorizo)\b",
        name,
    ):
        return CATEGORIES[4]
    if re.search(
        r"\b(chicken|beef|lamb|pork|turkey|duck|steak|mince|sausages|sausage)\b", name
    ):
        return CATEGORIES[1]
    if re.search(
        r"\b(fish|salmon|cod|haddock|tuna|prawn|prawns|mackerel|trout|seafood)\b", name
    ):
        return CATEGORIES[2]
    if re.search(
        r"\b(onion|carrot|pepper|broccoli|spinach|lettuce|tomato|lemon|lime|garlic|ginger|aubergine|potato|cabbage|salad|herbs?|courgette|peas|greens|leaf|leaves|apples?|avocados?|cucumbers?|mushrooms?|celery|coriander|parsley|basil)\b",
        name,
    ):
        return CATEGORIES[3]
    # Unknown foods are not assumed to keep for a whole month.
    return CATEGORIES[4]


def week_starts(first, last):
    current = planner.current_week_sunday(first)
    while current <= last:
        yield current
        current += timedelta(days=7)


def read_week(start):
    path = planner.plan_path(start)
    if not path.exists():
        return None

    def valid(plan):
        if (
            not isinstance(plan, dict)
            or not isinstance(plan.get("meals"), list)
            or len(plan["meals"]) > 7
        ):
            raise ValueError("Invalid saved weekly menu.")
        seen = set()
        for meal in plan["meals"]:
            if not isinstance(meal, dict):
                raise ValueError("Invalid saved meal.")
            if meal.get("kind") == "recipe":
                r = meal.get("recipe", {})
                if (
                    not isinstance(r, dict)
                    or not isinstance(r.get("name"), str)
                    or not isinstance(r.get("ingredients", []), list)
                    or any(not isinstance(v, str) for v in r.get("ingredients", []))
                ):
                    raise ValueError("Invalid saved recipe.")
            on = date.fromisoformat(meal["date"])
            if not start <= on <= start + timedelta(days=6) or on in seen:
                raise ValueError("Invalid weekly meal dates.")
            seen.add(on)
            if meal.get("kind") == "recipe" and not isinstance(
                meal.get("recipe"), dict
            ):
                raise ValueError("Invalid recipe.")

    return PrivateStore(path, default=dict, validate=valid, max_bytes=2000000).read()


def generate(raw, on=None):
    on = on or uk_today()
    first, last = bounds(raw)
    preferences()  # Fail closed before writing menus if dietary settings are damaged.
    if last < on:
        raise ValueError("Choose this month or a future month.")
    with file_lock(planner.PLANS_DIR / "monthly_generation"):
        # Read all existing files before creating anything; never replace damaged saved menus.
        starts = list(week_starts(max(first, on), last))
        saved = {start: read_week(start) for start in starts}
        recent = []
        updated = 0
        for start in starts:
            plan = saved[start]
            present = {m["date"] for m in (plan or {}).get("meals", [])}
            needed = {
                d.isoformat()
                for d in (start + timedelta(days=i) for i in range(7))
                if max(first, on) <= d <= last
            }
            if not needed <= present:
                plan = planner.generate_week(
                    start, raw=True, recent_names=recent, existing=plan, not_before=on
                )
                updated += 1
            recent.extend(
                m["recipe"]["name"] for m in plan["meals"] if m.get("kind") == "recipe"
            )
        store().update(lambda s: s.update(active_month=raw))
    return updated


def change_meal(raw, day, name, on=None):
    on = on or uk_today()
    first, last = bounds(raw)
    chosen = date.fromisoformat(day)
    if not max(first, on) <= chosen <= last:
        raise ValueError("Choose an upcoming day in this month.")
    from web_control.live_data import meal_confirmation

    if meal_confirmation(chosen):
        raise ValueError("This meal is already confirmed eaten.")
    recipe = next((r for r in planner.recipes() if r.get("name") == name), None)
    if not recipe or not planner._eligible(recipe, chosen, preferences()):
        raise ValueError(
            "Choose a recipe that meets your diet, allergens and cooking-time settings."
        )
    with file_lock(planner.PLANS_DIR / "monthly_generation"):
        start = planner.current_week_sunday(chosen)
        plan = read_week(start)
        if not plan:
            raise ValueError("Create the monthly menu first.")
        if not any(m["date"] == day for m in plan["meals"]):
            raise ValueError("This day is not in the saved week.")
        plan["meals"] = [
            dict(date=day, kind="recipe", recipe=recipe) if m["date"] == day else m
            for m in plan["meals"]
        ]
        plan["shopping"] = planner.build_shopping_list(plan)
        plan["prep"] = planner.build_sunday_prep(plan)
        plan["estimated_cost"] = planner.estimate_week_cost(plan)
        planner._save(planner.plan_path(start), plan)


def requirements(meals, on):
    from meals.remaining import needs_dinner
    from receipt.lifestyle import skip_meal

    rows = []
    for meal in meals:
        if meal.get("kind") != "recipe":
            continue
        day = date.fromisoformat(meal["date"])
        recipe = meal["recipe"]
        if needs_dinner(meal, on):
            rows.extend(
                dict(day=day, line=line, recipe=recipe["name"], scope="Dinner")
                for line in recipe.get("ingredients", [])
                if str(line).strip()
            )
            # A skipped/eaten/away dinner does not create fresh leftovers to buy for.
            lunch_day = day + timedelta(days=1)
            override = planner._override_for(lunch_day, "lunch")
            if (
                lunch_day >= on
                and not skip_meal(lunch_day)
                and not (override and override.get("type") in {"buy_lunch", "eat_out"})
            ):
                rows.extend(
                    dict(
                        day=lunch_day,
                        line=line,
                        recipe=recipe["name"],
                        scope="Next-day lunch",
                    )
                    for line in recipe.get("lunch", {}).get("extra_ingredients", [])
                    if str(line).strip()
                )
    return rows


def component_purchases(meals, resources, weeks=None):
    """Bought components omitted from main ingredients remain explicit shopping needs."""
    choices = {}
    if weeks is None:
        grouped = defaultdict(list)
        for meal in meals:
            grouped[
                planner.current_week_sunday(date.fromisoformat(meal["date"]))
            ].append(meal)
        weeks = [{"meals": rows} for rows in grouped.values()]
    for week in weeks:
        actions = {
            item["id"]: item["action"] for item in planner.build_sunday_prep(week)
        }
        for meal in week["meals"]:
            for cid, action in actions.items():
                choices[(meal["date"], cid)] = action
    lookup = {m["date"]: m for m in meals if m.get("kind") == "recipe"}
    rows = []
    for batch in resources["batches"]:
        for use in batch["uses"]:
            if choices.get((use["day"], batch["id"])) != "buy":
                continue
            recipe = lookup[use["day"]]["recipe"]
            if any(
                batch["name"].casefold() in line.casefold()
                for line in recipe.get("ingredients", [])
            ):
                continue
            rows.append(
                dict(
                    day=date.fromisoformat(use["day"]),
                    line=use["amount"] or batch["name"] + " (amount unspecified)",
                    recipe=use["recipe"] + " · bought component",
                    scope="Bought component",
                )
            )
    return rows


def shopping(rows, settings, first, on):
    start = max(first, on)
    grouped = defaultdict(list)
    items = defaultdict(list)
    for row in rows:
        key = identity(row["line"])
        kind = settings["overrides"].get(key) or category(row["line"])
        shop = settings["shops"][kind]
        need = row["day"]
        if kind == CATEGORIES[0]:
            buy = start
        else:
            weekdays = [settings["weekly_day"]]
            if kind == CATEGORIES[3] and settings["veg_topup"]:
                weekdays.append(settings["veg_day"])
            buy = max(
                start,
                max(need - timedelta(days=(need.weekday() - w) % 7) for w in weekdays),
            )
        grouped[(buy, shop)].append(row)
        items[key].append(dict(row, category=kind, shop=shop))
    visits = []
    for (buy, shop), uses in sorted(grouped.items()):
        byname = defaultdict(list)
        for row in uses:
            byname[identity(row["line"])].append(row)
        entries = []
        for key, lines in sorted(byname.items()):
            entries.append(
                dict(
                    key=key,
                    amounts=aggregate([r["line"] for r in lines], for_shopping=True),
                    needs=sorted({r["day"].isoformat() for r in lines}),
                    recipes=sorted({r["recipe"] for r in lines}),
                    unmeasured=any(parse(r["line"]) is None for r in lines),
                    pantry=planner._pantry_has(lines[0]["line"]),
                )
            )
        visits.append(dict(day=buy, shop=shop, items=entries))
    ingredient_choices = [
        dict(key=k, label=k, category=v[0]["category"])
        for k, v in sorted(items.items())
    ]
    return dict(
        visits=visits,
        ingredients=ingredient_choices,
        shopping_days=len({v["day"] for v in visits}),
        stops=len(visits),
        supermarket_stops=sum(v["shop"] in (SHOPS[0], SHOPS[4]) for v in visits),
    )


def report(raw, on=None):
    on = on or uk_today()
    first, last = bounds(raw)
    meals = []
    weeks = []
    missing = []
    for start in week_starts(first, last):
        plan = read_week(start)
        if plan:
            weeks.append(plan)
            meals.extend(
                m
                for m in plan["meals"]
                if first <= date.fromisoformat(m["date"]) <= last
            )
    lookup = {m["date"]: m for m in meals}
    prefs = preferences()
    days = []
    from receipt.lifestyle import skip_meal

    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        meal = lookup.get(day.isoformat())
        away = skip_meal(day)
        if day >= on and not meal and not away:
            missing.append(day)
        days.append(
            dict(
                day=day,
                meal=meal,
                away=away,
                past=day < on,
                needs_review=bool(
                    meal
                    and meal.get("kind") == "recipe"
                    and not planner._eligible(meal["recipe"], day, prefs)
                ),
            )
        )
    rows = requirements(meals, on)
    # Include the last day's planned leftover lunch even when it falls in the next month.
    config = store().read()
    from meals.resource_planning import analyse
    from actions.personal_helper import store as helper_store

    resources = analyse(
        dict(meals=meals),
        planner._load(planner.COMPONENTS_FILE, {}).get("components", []),
        helper_store().read()["meal_uses"],
        on,
    )
    rows.extend(component_purchases(meals, resources, weeks))
    shops = shopping(rows, config, first, on)
    from meals.remaining import needs_dinner

    costs = planner.estimate_week_cost(
        dict(
            meals=[
                m
                for m in meals
                if (
                    needs_dinner(m, on)
                    if m.get("kind") == "recipe"
                    else date.fromisoformat(m["date"]) >= on
                    and not skip_meal(date.fromisoformat(m["date"]))
                )
            ]
        )
    )
    return dict(
        month=raw,
        label=first.strftime("%B %Y"),
        first=first,
        last=last,
        days=days,
        missing=missing,
        config=config,
        resources=resources,
        cost=costs,
        **shops,
    )
