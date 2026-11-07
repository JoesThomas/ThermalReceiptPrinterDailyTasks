"""Sourced UK population references and explainable meal-selection preferences.

Energy values: SACN 2011 Tables 15/16 (printed pp84/85), population EARs.
No individual targets, calorie deficits or calorie-driven portion restriction.
"""

from datetime import date
import re
from meals.ingredients import parse

ENERGY_SOURCE = "https://www.gov.uk/government/publications/sacn-dietary-reference-values-for-energy"
BALANCE_SOURCE = "https://www.nhs.uk/live-well/eat-well/food-guidelines-and-food-labels/the-eatwell-guide/"
SEASON_SOURCE = (
    "https://www.soilassociation.org/what-we-do/championing-organic/seasonal-food/"
)
CHECKED = "2026-11-07"
# Factual data transcribed from SACN tables; these are not personal intake prescriptions.
CHILD_M = (
    765,
    1004,
    1171,
    1386,
    1482,
    1577,
    1649,
    1745,
    1840,
    2032,
    2127,
    2247,
    2414,
    2629,
    2820,
    2964,
    3083,
    3155,
)
CHILD_F = (
    717,
    932,
    1076,
    1291,
    1362,
    1482,
    1530,
    1625,
    1721,
    1936,
    2032,
    2103,
    2223,
    2342,
    2390,
    2414,
    2462,
    2462,
)
ADULTS = (
    (24, 2772, 2175),
    (34, 2749, 2175),
    (44, 2629, 2103),
    (54, 2581, 2103),
    (64, 2581, 2079),
    (74, 2342, 1912),
    (130, 2294, 1840),
)
# Broad UK seasonal availability, including common stored winter crops, not live shop stock.
SEASONS = {
    "spring": {
        "asparagus",
        "cauliflower",
        "lettuce",
        "broccoli",
        "cabbage",
        "radish",
        "rhubarb",
        "spinach",
        "spring onion",
        "watercress",
        "parsley",
    },
    "summer": {
        "aubergine",
        "blackcurrant",
        "blueberry",
        "broad bean",
        "cherry",
        "courgette",
        "cucumber",
        "gooseberry",
        "new potato",
        "onion",
        "peach",
        "pepper",
        "plum",
        "raspberry",
        "redcurrant",
        "rocket",
        "spinach",
        "spring onion",
        "strawberry",
        "watercress",
        "parsley",
    },
    "autumn": {
        "apple",
        "blackberry",
        "broccoli",
        "cabbage",
        "carrot",
        "celery",
        "chard",
        "courgette",
        "fennel",
        "fig",
        "garlic",
        "kale",
        "leek",
        "lettuce",
        "parsnip",
        "pear",
        "pepper",
        "plum",
        "potato",
        "onion",
        "spinach",
        "sweetcorn",
        "turnip",
        "squash",
        "pumpkin",
    },
    "winter": {
        "apple",
        "brussels sprout",
        "cabbage",
        "kale",
        "carrot",
        "cauliflower",
        "celeriac",
        "artichoke",
        "leek",
        "parsnip",
        "pear",
        "potato",
        "spring onion",
        "swede",
        "turnip",
    },
}
ALL_PRODUCE = set().union(*SEASONS.values())


def ages(person, on):
    year = person.get("birth_year")
    return (max(0, on.year - year - 1), on.year - year) if year else None


def energy(person, on):
    span = ages(person, on)
    if not span:
        return dict(
            ages=None,
            low=None,
            high=None,
            note="Add a birth year for an approximate age-based reference.",
        )
    if person.get("clinical") or span[0] < 2:
        return dict(
            ages=span,
            low=None,
            high=None,
            note="Separate individual feeding/dietary advice is needed; no automatic energy figure.",
        )
    values = []
    for age in set(span):
        if age <= 18:
            pair = (CHILD_M[age - 1], CHILD_F[age - 1])
        else:
            pair = next((m, f) for limit, m, f in ADULTS if age <= limit)
        values.extend(
            pair
            if person["reference"] == "range"
            else [pair[0 if person["reference"] == "male" else 1]]
        )
    return dict(
        ages=span,
        low=min(values),
        high=max(values),
        note="SACN population reference, not an individual target. Birth year gives an age range; activity, growth and health vary. Adult table uses population PAL 1.63.",
    )


def season(on):
    return ("winter", "spring", "summer", "autumn")[on.month % 12 // 3]


def produce(recipe):
    found = set()
    for line in recipe.get("ingredients", []):
        if re.search(
            r"\b(frozen|tinned|canned|dried|powder|granules|puree|purée)\b", line, re.I
        ):
            continue
        name = (parse(line) or (0, "", line.casefold()))[2]
        for crop in sorted(ALL_PRODUCE, key=len, reverse=True):
            pattern = (
                r"\b(?:"
                + re.escape(crop)
                + r"s?"
                + ("|" + re.escape(crop[:-1]) + "ies" if crop.endswith("y") else "")
                + r")\b"
            )
            if re.search(pattern, name):
                found.add(crop)
                name = re.sub(pattern, "", name)
    return found


def signals(recipe):
    text = " ".join(recipe.get("ingredients", [])).casefold()
    protein = str(recipe.get("balance", {}).get("protein", "")).casefold()
    return dict(
        plant=bool(
            re.search(
                r"\b(bean|beans|lentils?|chickpeas?|tofu|falafel)\b",
                text + " " + protein,
            )
        ),
        fish=bool(
            re.search(
                r"\b(fish|salmon|mackerel|sardines?|trout|cod|tuna|prawns?)\b", text
            )
        ),
        oily=bool(re.search(r"\b(salmon|mackerel|sardines?|trout)\b", text)),
        red=bool(re.search(r"\b(beef|lamb|pork|steak|bacon|ham|sausages?)\b", text)),
        processed=bool(re.search(r"\b(bacon|ham|salami|chorizo|sausages?)\b", text)),
        wholegrain=bool(
            re.search(r"\b(wholegrain|wholemeal|wholewheat|oats|brown rice)\b", text)
        ),
        produce=bool(
            produce(recipe)
            or re.search(r"\b(fruit|vegetables|frozen peas|greens|salad)\b", text)
        ),
    )


def score(recipe, chosen, on, settings):
    value = 0.0
    found = produce(recipe)
    if settings["seasonal"] and found:
        value += 4 * len(found & SEASONS[season(on)]) / len(found) - min(
            2, len(found - SEASONS[season(on)])
        )
    if settings["balanced"]:
        flags = signals(recipe)
        previous = [
            signals(m["recipe"])
            for m in chosen
            if m.get("kind") == "recipe"
            and (on - date.fromisoformat(m["date"])).days < 7
        ]
        value += (
            int(flags["wholegrain"])
            + int(flags["produce"])
            - 2 * int(flags["processed"])
        )
        if flags["plant"] and sum(p["plant"] for p in previous) < 2:
            value += 3
        if flags["fish"] and sum(p["fish"] for p in previous) < 2:
            value += 2
        if flags["oily"] and not any(p["oily"] for p in previous):
            value += 3
        if flags["red"] and sum(p["red"] for p in previous) >= 2:
            value -= 4
    return value


def overview(meals):
    values = [signals(m["recipe"]) for m in meals if m.get("kind") == "recipe"]
    return {
        key: sum(v[key] for v in values)
        for key in (
            "plant",
            "fish",
            "oily",
            "red",
            "processed",
            "wholegrain",
            "produce",
        )
    }
