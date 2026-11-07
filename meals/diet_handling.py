"""Household food handling prompts shared by Meals, shopping and paper."""

FSA = "https://www.food.gov.uk/print/pdf/node/22201"
COELIAC_UK = "https://www.coeliac.org.uk/living-with-coeliac-disease/food-and-drink/cooking-at-home/cross-contamination/"
ALLERGEN_NAMES = {
    "milk": "milk / dairy",
    "cereals_containing_gluten": "cereals containing gluten",
}


def guidance(prefs):
    """Describe checks, never mark an ingredient, kitchen or dish as verified."""
    s = prefs.get("_household", {})
    people = s.get("people", ()) if s.get("configured") else ()
    excluded = set(prefs.get("excluded_allergens", ()))
    for person in people:
        excluded.update(person["allergens"])
    coeliac = any(p.get("coeliac") for p in people)
    manual = any(p.get("clinical") or p.get("notes") for p in people)
    diets = sorted(
        {p["diet"] for p in people if p["diet"] != "omnivore"}
        | ({"vegetarian"} if prefs.get("vegetarian_only") else set())
        | ({"vegan"} if prefs.get("vegan_only") else set())
    )
    if not (
        coeliac or excluded or diets or manual or any(p.get("avoid") for p in people)
    ):
        return None

    shopping = "Check the exact product each time, including sauces, stocks, toppings, substitutions, ingredient lists and relevant ‘may contain’ warnings. Check pantry and freezer items too."
    prep = "Wash hands and thoroughly clean worktops, boards, pans and utensils. Use separate equipment where it cannot be cleaned reliably. Use only checked ingredients, including oil, coatings and garnishes."
    if coeliac:
        shopping += " Use gluten-free labelled substitutes; only use oats labelled gluten-free if tolerated."
        prep += " For gluten-free toast use a separate toaster or toaster bag; avoid shared fryer oil, pasta water and crumb-contaminated spreads."
    return dict(
        diets=diets,
        allergens=[
            ALLERGEN_NAMES.get(a, a.replace("_", " ")) for a in sorted(excluded)
        ],
        coeliac=coeliac,
        manual=manual,
        shopping=shopping,
        stages=[
            ("Buy and check", shopping),
            (
                "Store",
                "Keep checked ingredients and prepared portions sealed, labelled and separate from foods they must avoid, including in the fridge and freezer. Follow normal temperature and use-by guidance.",
            ),
            ("Prep and cook", prep),
            (
                "Serve",
                "Use clean plates and separate serving utensils. Check sauces, sides and toppings before serving. If an unsuitable ingredient has touched the dish, make a fresh portion.",
            ),
            (
                "Pack leftovers",
                "Set aside tomorrow’s lunch before serving. Label the container with the dish, date and dietary requirements; keep it separate when chilling, freezing and reheating.",
            ),
            (
                "Check meals out and freezer meals",
                "Confirm ingredients and preparation with the provider, or check the stored batch and label. If you cannot confirm suitability, choose another meal.",
            ),
        ],
        sources=[("Food Standards Agency", FSA)]
        + ([("Coeliac UK", COELIAC_UK)] if coeliac else []),
    )


def receipt_lines(view):
    if not view:
        return []
    return [
        "Check labels, pantry and swaps.",
        "Store sealed, labelled and separate.",
        "Use clean tools, surfaces and plates.",
        "Check sides; pack lunch before serving.",
        *(["Gluten-free: avoid crumbs/shared oil."] if view["coeliac"] else []),
        *(["Review household dietary notes in Meals."] if view["manual"] else []),
    ]
