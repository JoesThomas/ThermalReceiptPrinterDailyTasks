"""Quick weekday breakfasts and calendar-aware weekend choices; no network on reads."""

from copy import deepcopy
from datetime import datetime, date, time, timedelta, timezone
from receipt.local_time import UK, uk_today
from storage import read_json_object
from meals import household


def recipe(
    name, minutes, ingredients, method, allergens=(), vegan=False, calories=None
):
    return dict(
        name=name,
        slot="breakfast",
        total_minutes=minutes,
        cook_servings=1,
        servings=1,
        meal_type="single",
        ingredients=ingredients,
        method=method,
        allergens={"uk_14": list(allergens)},
        dietary={"vegetarian": True, "vegan": vegan},
        nutrition_per_serving={"calories": calories},
        prep_components=[],
    )


def catalogue(on=None, s=None):
    on = on or uk_today()
    s = s or household.store().read()
    # Explicit concrete fruit, chosen before dietary filtering; preserved fruit is neutral in spring.
    fruit = "1 apple"
    if s["seasonal"] and on.month in (6, 7, 8):
        fruit = "80g strawberries"
    elif s["seasonal"] and on.month in (3, 4, 5):
        fruit = "80g tinned peaches in juice"
    meals = [
        recipe(
            "Wholegrain cereal & fruit",
            3,
            ["40g wholegrain cereal", "200ml milk", fruit],
            ["Choose a lower-sugar cereal; add milk and prepared fruit."],
            ("cereals_containing_gluten", "milk"),
            calories=340,
        ),
        recipe(
            "Cereal, fortified soya drink & fruit",
            3,
            ["40g wholegrain cereal", "200ml calcium-fortified soya drink", fruit],
            ["Check the cereal and drink labels; serve with prepared fruit."],
            ("cereals_containing_gluten", "soybeans"),
            True,
            320,
        ),
        recipe(
            "Quick porridge & fruit",
            5,
            ["45g oats", "200ml milk", fruit],
            [
                "Cook oats with milk following the packet instructions; add prepared fruit."
            ],
            ("cereals_containing_gluten", "milk"),
            calories=350,
        ),
        recipe(
            "Gluten-free porridge & fruit",
            5,
            ["45g certified gluten-free oats", "200ml water", fruit],
            [
                "Use certified gluten-free oats and follow the packet cooking instructions; serve with prepared fruit."
            ],
            (),
            True,
            250,
        ),
        recipe(
            "Yoghurt, muesli & fruit",
            3,
            ["150g plain yoghurt", "40g nut-free muesli", fruit],
            [
                "Use a lower-sugar, nut-free muesli and plain yoghurt; add fruit. Check all labels."
            ],
            ("milk", "cereals_containing_gluten"),
            calories=330,
        ),
        recipe(
            "Soya yoghurt, oats & fruit",
            3,
            [
                "150g calcium-fortified soya yoghurt",
                "40g certified gluten-free oats",
                fruit,
            ],
            [
                "Use ready-to-eat oats whose label permits eating without cooking; combine with yoghurt and prepared fruit."
            ],
            ("soybeans",),
            True,
            310,
        ),
        recipe(
            "Beans on wholemeal toast",
            10,
            [
                "150g ready-to-eat tinned baked beans",
                "2 slices wholemeal bread",
                "100g tomatoes",
            ],
            [
                "Heat the beans as instructed on the pack, toast the bread and serve with prepared tomatoes."
            ],
            ("cereals_containing_gluten",),
            True,
            360,
        ),
        recipe(
            "Scrambled eggs & toast",
            15,
            ["2 eggs", "2 slices wholemeal bread", "1 tsp olive oil", "100g tomatoes"],
            [
                "Toast the bread. Cook the beaten eggs gently in the oil until set; serve with tomatoes."
            ],
            ("eggs", "cereals_containing_gluten"),
            calories=410,
        ),
        recipe(
            "Mushrooms, spinach & toast",
            20,
            [
                "150g mushrooms",
                "80g spinach",
                "2 slices wholemeal bread",
                "1 tsp olive oil",
            ],
            [
                "Cook the prepared mushrooms in oil; add spinach and cook through. Serve on toast."
            ],
            ("cereals_containing_gluten",),
            True,
            310,
        ),
        recipe(
            "Weekend vegetable omelette",
            25,
            [
                "2 eggs",
                "80g spinach",
                "100g mushrooms",
                "2 slices wholemeal bread",
                "1 tsp olive oil",
            ],
            [
                "Cook the prepared vegetables in oil; add beaten eggs and cook until set. Serve with toast."
            ],
            ("eggs", "cereals_containing_gluten"),
            calories=430,
        ),
    ]
    return meals + [deepcopy(r) for r in s["custom"] if r["slot"] == "breakfast"]


def fresh(stamp, now):
    from services.day_travel import when

    dt = when(stamp)
    return bool(
        dt and 0 <= (now - dt.astimezone(timezone.utc)).total_seconds() <= 86400
    )


def snapshot():
    from web_control.today_summary import CALENDAR
    from services.day_travel import store

    try:
        travel = store().read()
    except (ValueError, OSError):
        travel = {"days": {}}
    return read_json_object(CALENDAR), travel


def context(on, now=None, saved_snapshot=None):
    from services.day_travel import when

    now = (now or datetime.now(UK)).astimezone(timezone.utc)
    state, travel = saved_snapshot or snapshot()
    saved = travel["days"].get(on.isoformat(), {})
    covered = (
        state.get("coverage_from", "") <= on.isoformat() <= state.get("coverage_to", "")
    )
    verified = bool(
        covered
        and fresh(state.get("checked_at"), now)
        and state.get("status") == "checked"
        and not state.get("warnings")
    )
    events = state.get("events", []) if verified else []
    if (
        fresh(saved.get("checked"), now)
        and not saved.get("warnings")
        and (not verified or when(saved["checked"]) >= when(state["checked_at"]))
    ):
        events = [dict(e, date=on.isoformat()) for e in saved.get("events", [])]
        verified = True
    plan = saved.get("plan", {})
    if not fresh(plan.get("checked"), now) or plan.get("day") != on.isoformat():
        plan = {}
    from actions.personal_helper import calendar_signature

    if plan and calendar_signature(events, on) != calendar_signature(
        saved.get("events", []), on
    ):
        plan = {}
    if plan and any(
        not when(leg.get("depart")) or not when(leg.get("arrive"))
        for leg in plan.get("legs", [])
    ):
        plan = {}
    return dict(verified=verified, events=events, plan=plan)


def windows(on, s, calendar):
    from services.day_travel import when

    begin = datetime.combine(on, time.fromisoformat(s["breakfast_start"]), UK)
    end = datetime.combine(on, time.fromisoformat(s["breakfast_end"]), UK)
    busy = []
    for e in calendar["events"]:
        day = str(e.get("date", ""))[:10]
        if e.get("all_day") and day == on.isoformat():
            busy.append((begin, end))
            continue
        a = when(e.get("start_dt") or e.get("start"))
        b = when(e.get("end_dt") or e.get("end"))
        if not a or a >= end or b and b <= begin:
            continue
        if not b or b <= a:
            b = end
        if e.get("location", e.get("address", "")) and not calendar["plan"]:
            a -= timedelta(minutes=30)
        busy.append((a, b))
    for leg in calendar["plan"].get("legs", []):
        a = when(leg.get("depart"))
        b = when(leg.get("arrive"))
        if a and b and b >= a:
            busy.append((a, b))
    free = []
    cursor = begin
    for a, b in sorted(busy) + [(end, end)]:
        a = max(a, begin)
        b = min(b, end)
        if a > cursor:
            free.append((cursor, a))
        cursor = max(cursor, b)
    return free


def plan(on, s=None, calendar=None):
    from meals import legacy_planner
    from meals.nutrition_guidance import score
    from receipt.lifestyle import skip_meal

    s = s or household.store().read()
    if (
        not s["breakfast_enabled"]
        or skip_meal(on)
        or not household.diners(s, on, "breakfast")
    ):
        return None
    calendar = calendar or context(on)
    prefs = legacy_planner.preferences()
    weekend = on.weekday() >= 5
    available = windows(on, s, calendar)
    from services.day_travel import when

    window_end = datetime.combine(on, time.fromisoformat(s["breakfast_end"]), UK)
    missing_travel = not calendar["plan"] and any(
        e.get("location", e.get("address", ""))
        and (a := when(e.get("start_dt") or e.get("start")))
        and a.date() == on
        and a < window_end
        for e in calendar["events"]
    )
    limit = s["weekday_minutes"]
    if (
        weekend
        and not missing_travel
        and (calendar["verified"] or s["provisional_weekends"])
    ):
        limit = s["weekend_minutes"]
        if calendar["verified"]:
            limit = min(
                limit,
                max(
                    [
                        int((b - a).total_seconds() // 60) - s["eating_minutes"]
                        for a, b in available
                    ]
                    or [0]
                ),
            )
    candidates = [
        r
        for r in catalogue(on, s)
        if legacy_planner._eligible(r, on, prefs, slot="breakfast")
        and household.permitted(r, s, on, "breakfast")
    ]
    manual = s["breakfast_overrides"].get(on.isoformat())
    chosen = next((r for r in candidates if r["name"] == manual), None)
    if chosen is None:
        pool = [r for r in candidates if r["total_minutes"] <= limit]
        if not pool:
            pool = [r for r in candidates if r["total_minutes"] <= s["weekday_minutes"]]
        if not pool:
            return dict(
                unavailable=True,
                note="No enabled breakfast meets the dietary and time settings. Review the selection.",
                done=on.isoformat() in s["breakfast_done"],
                options=[r["name"] for r in candidates],
            )
        if weekend and limit > s["weekday_minutes"]:
            leisurely = [r for r in pool if r["total_minutes"] > s["weekday_minutes"]]
            if leisurely:
                pool = leisurely
        # Rotate deterministically among similarly suitable options; independent of page reads.
        ranked = sorted(pool, key=lambda r: (-score(r, [], on, s), r["name"]))
        best = score(ranked[0], [], on, s)
        pool = [r for r in ranked if score(r, [], on, s) >= best - 2]
        chosen = pool[on.toordinal() % len(pool)]
    needed = chosen["total_minutes"] + s["eating_minutes"]
    slot = next(
        (
            (a, a + timedelta(minutes=needed))
            for a, b in available
            if (b - a).total_seconds() >= needed * 60
        ),
        None,
    )
    note = (
        "Uses a current saved calendar window, including available travel times."
        if calendar["verified"]
        else "Calendar coverage is unverified; quick fallback unless provisional weekends are enabled."
    )
    if missing_travel:
        note = "Morning travel time is unverified; a provisional buffer is used and a quick breakfast is preferred."
    if manual and chosen["total_minutes"] > limit:
        note += " Your explicit choice exceeds the automatic preparation limit."
    if not slot:
        note = "No verified fitting breakfast window. This is a food suggestion; check when you can eat."
    return dict(
        recipe=household.prepare(chosen, on, s, slot="breakfast"),
        start=slot[0] if slot and calendar["verified"] and not missing_travel else None,
        end=slot[1] if slot and calendar["verified"] and not missing_travel else None,
        note=note,
        verified=calendar["verified"],
        manual=bool(chosen["name"] == manual),
        done=on.isoformat() in s["breakfast_done"],
        unavailable=False,
        options=[r["name"] for r in candidates],
    )


def receipt_lines(on):
    result = plan(on)
    if not result or result["done"]:
        return []
    if result["unavailable"]:
        return ["Breakfast: check meal settings"]
    r = result["recipe"]
    count = r.get("_household_diners", 1)
    return [
        f"Breakfast: {r['name']}",
        f"{count} diner(s); about {r['total_minutes']} min. Details in Meals.",
    ]
