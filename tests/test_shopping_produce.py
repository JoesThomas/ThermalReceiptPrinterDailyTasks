"""Shopping suggestions retain original amounts and explicitly chosen products."""

from unittest import TestCase
from meals.ingredients import shopping_amount, shopping_key, shopping_produce_note


class ShoppingProduceTests(TestCase):
    def test_leaf_estimates_sum_household_scales_and_exact_weights(self):
        lines = [
            "handful of leafy greens (unmeasured; scale for 2x)",
            "handful of leafy greens (unmeasured; scale for 3x)",
            "50g leafy greens",
        ]
        self.assertEqual({shopping_key(line) for line in lines}, {"leafy greens"})
        self.assertEqual(shopping_amount("leafy greens", lines, pack_sizes={}),
                         "Approx. 175 g baby spinach (suggested)")
        self.assertIn("25 g per handful", shopping_produce_note("leafy greens", lines))
        self.assertEqual(lines[-1], "50g leafy greens")

    def test_salad_spinach_and_lettuce_stay_distinct(self):
        for key, line, expected in [
            ("salad leaves", "handful of salad leaves", "Approx. 25 g mixed salad leaves"),
            ("spinach", "2 handfuls of spinach", "Approx. 50 g spinach"),
            ("lettuce", "handful of lettuce (unmeasured; scale for 3x)", "Approx. 75 g lettuce"),
        ]:
            self.assertEqual(shopping_amount(key, [line], pack_sizes={}), expected)
        self.assertEqual(shopping_amount("spinach", ["spinach"], pack_sizes={}),
                         "spinach (check amount)")
        self.assertEqual(shopping_amount("spinach", ["100g spinach"], pack_sizes={}),
                         "100 g spinach")
        self.assertEqual(shopping_amount("frozen spinach", ["100g frozen spinach"], pack_sizes={}),
                         "100 g frozen spinach")

    def test_unsupported_leaf_amounts_remain_visible(self):
        self.assertEqual(shopping_amount("salad leaves", ["handful of salad leaves", "salad leaves"], pack_sizes={}),
                         "Approx. 25 g mixed salad leaves (check extra amount)")

    def test_tomato_suggestions_preserve_counts_and_named_varieties(self):
        self.assertEqual(shopping_amount("tomato", ["2 tomatoes"], pack_sizes={}, recipes=["Tomato Salad"]),
                         "2 medium round tomatoes (suggested)")
        self.assertEqual(shopping_amount("tomato", ["250g tomatoes"], pack_sizes={}, recipes=["Tomato Salad"]),
                         "250 g cherry tomatoes (suggested)")
        self.assertEqual(shopping_amount("tomato", ["250g tomatoes"], pack_sizes={}, recipes=["Tomato Sauce"]),
                         "250 g plum tomatoes (suggested)")
        self.assertEqual(shopping_amount("tomato", ["250g tomatoes"], pack_sizes={}, recipes=["Salad", "Curry"]),
                         "250 g round tomatoes (suggested)")
        for variety in ("cherry", "piccolo", "beef", "tinned", "sun-dried"):
            self.assertEqual(shopping_amount(variety + " tomato", ["100g " + variety + " tomatoes"], pack_sizes={}),
                             "100 g " + variety + " tomatoes")

    def test_audited_beef_dishes_use_the_correct_cut(self):
        from meals.ingredients import recipe_ingredient
        self.assertEqual(recipe_ingredient("150g lean beef", "Quick Beef Bolognese"),
                         "150g lean beef mince")
        self.assertEqual(recipe_ingredient("150g lean beef", "Beef Broccoli Noodles"),
                         "150g lean beef strips")
        self.assertEqual(recipe_ingredient("150g lean beef", "Beef Stew"),
                         "150g lean stewing beef")
        self.assertEqual(recipe_ingredient("150g lean beef", "Custom dish"), "150g lean beef")
        self.assertEqual(recipe_ingredient("150g diced beef", "Quick Beef Bolognese"), "150g diced beef")

    def test_catalogue_has_specific_produce_and_beef_ingredients(self):
        import json
        from pathlib import Path
        from meals.ingredients import BEEF_CUTS, parse
        root = Path(__file__).resolve().parents[1]
        source = (root / "data/recipes.json").read_text()
        self.assertEqual(source, (root / "recipes.json").read_text())
        recipes = json.loads(source)["recipes"]
        vague = {"fresh herbs", "handful of leafy greens", "handful of salad leaves",
                 "handful of spinach", "handful of lettuce", "lettuce",
                 "handful of salad", "handful of slaw", "natural yoghurt"}
        for recipe in recipes:
            lines = recipe.get("ingredients", []) + recipe.get("lunch", {}).get("extra_ingredients", [])
            self.assertFalse(vague.intersection(lines), recipe["name"])
            self.assertFalse(any((row := parse(line)) and row[2] in {"lean beef", "tomato"}
                                 for line in lines), recipe["name"])
            if recipe["name"] in BEEF_CUTS:
                self.assertIn("150g " + BEEF_CUTS[recipe["name"]], lines)
        kofta = next(r for r in recipes if r["name"] == "Beef Kofta & Tahini Flatbread")
        self.assertTrue(any("shape" in step for step in kofta["method"]))
        self.assertIn("planning defaults", kofta["ingredient_notes"])

    def test_salad_examples_are_display_only_and_do_not_repeat(self):
        from meals.ingredients import ingredient_display
        line = "50g mixed salad leaves"
        display = ingredient_display(line)
        self.assertEqual(display, "50g mixed salad leaves (e.g. lettuce, rocket or baby spinach)")
        self.assertEqual(ingredient_display(display), display)
        self.assertEqual(ingredient_display("50g romaine lettuce"), "50g romaine lettuce")
        self.assertEqual(line, "50g mixed salad leaves")
        self.assertIn("not separate items", shopping_produce_note("mixed salad leaves", [line]))
