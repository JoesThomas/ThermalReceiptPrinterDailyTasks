"""Government-based reserve suggestions, not an invented complete emergency diet."""

from meals import household

SOURCE = "https://beready.campaign.gov.uk/be-ready-for-emergencies/"
BASELINE_DAYS = 3
BASELINE_WATER_LITRES = 3


def catalogue():
    return [
        dict(
            id="beans",
            name="Ready-to-eat tinned beans or lentils",
            ingredients=["ready-to-eat tinned beans"],
            allergens={"uk_14": []},
            dietary={"vegan": True, "vegetarian": True},
        ),
        dict(
            id="vegetables",
            name="Ready-to-eat tinned vegetables",
            ingredients=["ready-to-eat tinned vegetables"],
            allergens={"uk_14": []},
            dietary={"vegan": True, "vegetarian": True},
        ),
        dict(
            id="fruit",
            name="Tinned fruit in juice",
            ingredients=["tinned peaches in juice"],
            allergens={"uk_14": []},
            dietary={"vegan": True, "vegetarian": True},
        ),
        dict(
            id="crackers",
            name="Wholegrain crackers",
            ingredients=["wholegrain wheat crackers"],
            allergens={"uk_14": ["cereals_containing_gluten"]},
            dietary={"vegan": True, "vegetarian": True},
        ),
        dict(
            id="ricecakes",
            name="Gluten-free rice cakes",
            ingredients=["gluten-free rice cakes"],
            allergens={"uk_14": []},
            dietary={"vegan": True, "vegetarian": True},
        ),
        dict(
            id="fish",
            name="Ready-to-eat tinned fish",
            ingredients=["ready-to-eat tinned sardines"],
            allergens={"uk_14": ["fish"]},
            dietary={
                "vegan": False,
                "vegetarian": False,
                "contains_meat": False,
                "contains_fish_or_shellfish": True,
            },
        ),
        dict(
            id="meat",
            name="Ready-to-eat tinned meat",
            ingredients=["ready-to-eat tinned chicken"],
            allergens={"uk_14": []},
            dietary={"vegan": False, "vegetarian": False},
        ),
        dict(
            id="nuts",
            name="Unsalted nuts (not for under-fives)",
            ingredients=["whole nuts"],
            allergens={"uk_14": ["nuts"]},
            dietary={"vegan": True, "vegetarian": True},
        ),
        dict(
            id="milk",
            name="Single-serving UHT milk",
            ingredients=["UHT milk"],
            allergens={"uk_14": ["milk"]},
            dietary={"vegan": False, "vegetarian": True},
        ),
        dict(
            id="soya",
            name="Single-serving fortified soya drink",
            ingredients=["fortified soya drink"],
            allergens={"uk_14": ["soybeans"]},
            dietary={"vegan": True, "vegetarian": True},
        ),
    ]


def report(on, s=None):
    s = s or household.store().read()
    options = []
    # Reserve foods are filtered by every profile, but not by the dinner favourites list.
    filters = dict(s, dinners=None, breakfasts=None, configured=True)
    for r in catalogue() if household.shared(s, on) else []:
        if not household.permitted(r, filters, on):
            continue
        target = s["reserve_targets"].get(r["id"])
        have = s["reserve_have"].get(r["id"], 0)
        options.append(
            dict(
                r,
                target=target,
                have=have,
                missing=max(0, target - have) if target is not None else None,
            )
        )
    water = s["reserve_days"] * len(s["people"]) * s["water_litres"]
    return dict(
        options=options,
        days=s["reserve_days"],
        people=len(s["people"]),
        water=water,
        water_missing=max(0, water - s["water_have"]),
        notes=s["reserve_notes"],
        source=SOURCE,
        baseline_days=BASELINE_DAYS,
        baseline_water=BASELINE_WATER_LITRES,
        infant=any(
            (span := household.ages(p, on)) and span[0] < 2 for p in s["people"]
        ),
    )
