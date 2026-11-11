"""Pack-based freezer meals work with existing portions, diets and shopping."""

import json
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from meals import household, monthly
from meals.ingredients import parse


class FreezerConvenienceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.recipes = [
            r for r in json.loads((root / "data/recipes.json").read_text())["recipes"]
            if "freezer_convenience" in r.get("tags", [])
        ]

    def test_requested_and_similar_meals_have_explicit_sides_and_pack_methods(self):
        self.assertEqual(len(self.recipes), 9)
        for recipe in self.recipes:
            self.assertEqual(len(recipe["ingredients"]), 4)
            self.assertIn("80g frozen peas", recipe["ingredients"])
            self.assertIn("100g tinned baked beans", recipe["ingredients"])
            self.assertTrue(all(parse(line) for line in recipe["ingredients"]))
            self.assertFalse(recipe.get("lunch"))
            self.assertIn("packet", " ".join(recipe["method"]))
            self.assertEqual(recipe["nutrition_per_serving"], {})
            self.assertTrue(recipe["allergens"]["check_labels_for"])
        for kind in ("Pizza", "Fish Fingers", "Battered Fish", "Chicken Kiev"):
            self.assertTrue(any(kind in recipe["name"] for recipe in self.recipes))

    def test_household_scaling_and_shopping_combine_shared_sides(self):
        day = date(2026, 11, 14)
        settings = household.defaults()
        settings.update(configured=True)
        settings["people"].append(dict(household.person(), name="Second diner"))
        selected = self.recipes[:2]
        meals = [household.prepare(recipe, day, settings) for recipe in selected]
        self.assertIn("160g frozen peas", meals[0]["ingredients"])
        self.assertFalse(meals[0].get("lunch"))
        rows = [
            dict(day=day, recipe=recipe["name"], line=line)
            for recipe in meals for line in recipe["ingredients"]
        ]
        with patch.object(monthly.planner, "load_pantry_matcher", return_value=lambda line: False),              patch.object(monthly, "load_pack_sizes", return_value={}):
            view = monthly.shopping(rows, monthly.defaults(), day, day)
        self.assertEqual({visit["shop"] for visit in view["visits"]}, {"Main supermarket shop"})
        ingredients = {item["key"]: item for visit in view["visits"] for item in visit["items"]}
        self.assertEqual(ingredients["frozen peas"]["amount"], "320 g frozen peas")
        self.assertEqual(ingredients["tinned baked bean"]["amount"], "400 g tinned baked beans")

    def test_meat_fish_and_gluten_filters_are_respected(self):
        day = date(2026, 11, 14)
        settings = household.defaults()
        settings.update(configured=True)
        person = settings["people"][0]
        person["diet"] = "vegetarian"
        for recipe in self.recipes:
            self.assertEqual(household.permitted(recipe, settings, day),
                             recipe["dietary"]["vegetarian"], recipe["name"])
        person["diet"] = "pescatarian"
        for recipe in self.recipes:
            if recipe["dietary"]["contains_meat"]:
                self.assertFalse(household.permitted(recipe, settings, day))
        person["diet"] = "omnivore"
        person["coeliac"] = True
        self.assertTrue(all(not household.permitted(recipe, settings, day) for recipe in self.recipes))
