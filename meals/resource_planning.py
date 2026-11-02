"""Shared components, conservative prep grouping and equipment-based clean-up estimates."""

import re
from collections import defaultdict
from datetime import date

from meals.food_storage import _COMPONENTS
from meals.ingredients import aggregate, parse


def component_ids(recipe):
    return {
        r.get("id") if isinstance(r, dict) else r
        for r in recipe.get("prep_components", [])
        if r
    }


def fresh_ids(recipe):
    result = set()
    for line in recipe.get("ingredients", []):
        parsed = parse(line)
        name = parsed[2] if parsed else str(line).casefold()
        if any(
            x in name
            for x in (
                "onion",
                "pepper",
                "spinach",
                "greens",
                "lemon",
                "lime",
                "tomato",
                "yoghurt",
                "herb",
                "broccoli",
                "carrot",
                "lettuce",
            )
        ):
            result.add(name)
    return result


def window_days(cid):
    # Use the existing conservative storage guidance, not a new claim about shelf life.
    if cid == "shawarma_spice":
        return 6
    hours = _COMPONENTS.get(cid, (None, ""))[0]
    return max(0, hours // 24 - 1) if isinstance(hours, int) else 0


def reuse_bonus(recipe, chosen, on):
    bonus = 0
    components = component_ids(recipe)
    fresh = fresh_ids(recipe)
    for previous in chosen:
        age = (on - date.fromisoformat(previous["date"])).days
        if previous.get("kind") != "recipe":
            continue
        other = previous["recipe"]
        bonus += sum(
            3
            for cid in components & component_ids(other)
            if 0 <= age <= window_days(cid)
        )
        if 0 <= age <= 1:
            bonus += min(3, len(fresh & fresh_ids(other)))
    return min(bonus, 9)


def cleanup(recipe):
    equipment = set(recipe.get("equipment") or [])
    equipment.discard("oven")
    equipment.discard("hob")
    equipment.discard("worktop")
    raw = bool(
        re.search(
            r"\b(chicken|beef|pork|lamb|fish|salmon|turkey)\b",
            " ".join(recipe.get("ingredients", [])),
            re.IGNORECASE,
        )
    )
    equipment.update({"chopping board", "knife"})
    if raw:
        equipment.update({"separate ready-to-eat board", "separate ready-to-eat knife"})
    if any(
        x in " ".join(recipe.get("method", [])).casefold()
        for x in ("mix", "toss", "whisk")
    ):
        equipment.add("mixing bowl")
    count = len(equipment)
    return dict(
        level="Low" if count <= 3 else "Medium" if count <= 6 else "High",
        items=count,
        equipment=sorted(equipment),
        note="Equipment estimate, not wash cycles. Clean raw-food tools before reuse; no unwashed cross-use is suggested.",
    )


def amount_for(recipe, cid, component, overrides):
    explicit = overrides.get(recipe.get("name", "") + "|" + cid)
    if explicit:
        return explicit + " " + component.get("name", cid)
    for ref in recipe.get("prep_components", []):
        if (
            isinstance(ref, dict)
            and ref.get("id") == cid
            and ref.get("quantity") is not None
            and ref.get("unit")
        ):
            value = (
                str(ref["quantity"])
                + " "
                + str(ref["unit"])
                + " "
                + component.get("name", cid)
            )
            if parse(value):
                return value
    needle = component.get("name", cid).casefold()
    for ingredient in recipe.get("ingredients", []):
        if needle in ingredient.casefold() and parse(ingredient):
            return ingredient
    return None


def analyse(plan, components, overrides=None, today=None):
    from meals.remaining import needs_dinner
    from receipt.local_time import uk_today

    today = today or uk_today()
    overrides = overrides or {}
    byid = {c["id"]: c for c in components}
    uses = defaultdict(list)
    cleanups = []
    for meal in plan.get("meals", []):
        if not needs_dinner(meal, today):
            continue
        recipe = meal["recipe"]
        cleanups.append(dict(day=meal["date"], name=recipe["name"], **cleanup(recipe)))
        for cid in component_ids(recipe):
            if cid not in byid:
                continue
            uses[cid].append(
                dict(
                    day=meal["date"],
                    recipe=recipe["name"],
                    amount=amount_for(recipe, cid, byid[cid], overrides),
                )
            )
    batches = []
    for cid, rows in uses.items():
        groups = []
        for row in sorted(rows, key=lambda r: r["day"]):
            if not groups or (
                date.fromisoformat(row["day"])
                - date.fromisoformat(groups[-1][0]["day"])
            ).days > window_days(cid):
                groups.append([])
            groups[-1].append(row)
        for group in groups:
            quantities = aggregate([r["amount"] for r in group if r["amount"]])
            unknown = sum(not r["amount"] for r in group)
            batches.append(
                dict(
                    id=cid,
                    name=byid[cid].get("name", cid),
                    make=byid[cid].get("make", {}),
                    make_on=group[0]["day"],
                    uses=group,
                    quantities=quantities,
                    unknown=unknown,
                    note="Plan separate batches for later dates; actual preparation time and earlier ingredient labels still control storage.",
                )
            )
    return dict(
        batches=batches,
        cleanup=cleanups,
        shared=[
            dict(
                id=cid,
                name=byid[cid].get("name", cid),
                count=len(rows),
                recipes=[r["recipe"] for r in rows],
            )
            for cid, rows in uses.items()
            if len(rows) > 1
        ],
    )
