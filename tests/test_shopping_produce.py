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
