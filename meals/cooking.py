from __future__ import annotations
import re
from validation import load_json
from config import FILES

def _grams(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*g\b", text.lower())
    return float(m.group(1)) if m else None

def equipment():
    return load_json(FILES["equipment"], dict)

def rules():
    return load_json(FILES["cooking_rules"], dict)

def rice_method(rice_name: str, grams: float) -> dict:
    rule_id = "jasmine_rice" if "jasmine" in rice_name.lower() else "basmati_rice"
    rule = rules()[rule_id]
    cooker = equipment().get("rice_cooker", {})
    if isinstance(cooker, bool):
        cooker = {"owned": cooker}
    portion_g = float(rule.get("portion_g", 75))
    portions = grams / portion_g
    minimum = int(cooker.get("minimum_portions", 2) or 2)

    if cooker.get("owned") and portions >= minimum:
        return {
            "method": "rice_cooker",
            "summary": f"{grams:g}g {rule['display_name']} - rice cooker ({portions:g} portions).",
            "instructions": [
                "Rinse the rice as appropriate for the variety.",
                "Use the rice cooker's marked water level or manufacturer guidance for the measured amount.",
                "Start the rice cooker and leave it closed until the cycle finishes.",
                "Rest for 5-10 minutes if the cooker allows, then fluff before serving.",
            ],
        }

    pan = rule["saucepan"]
    water = round((grams / portion_g) * float(pan["water_ml_per_75g"]))
    return {
        "method": "saucepan",
        "summary": f"{grams:g}g {rule['display_name']} / ~{water}ml water.",
        "instructions": pan["instructions"],
    }

def cooking_guides(recipe: dict) -> list[dict]:
    guides = []
    for ingredient in recipe.get("ingredients", []):
        low = ingredient.lower()
        grams = _grams(ingredient)
        if grams and ("basmati rice" in low or "jasmine rice" in low):
            guides.append(rice_method(ingredient, grams))
    return guides
