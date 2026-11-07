from datetime import date
from unittest import TestCase

from meals.shopping_checklist import receipt_text


class ShoppingChecklistTests(TestCase):
    def test_thermal_width_and_one_box_per_item_even_when_wrapped(self):
        text = receipt_text(
            date(2026, 11, 7),
            "",
            ["2 packs of gluten-free pasta with a very long description", "1 apple"],
            columns=32,
        )
        self.assertIn("SUPERMARKET SHOPPING LIST", text)
        self.assertIn("Sat 07 Nov 2026", text)
        self.assertEqual(text.count("[ ]"), 2)
        self.assertTrue(all(len(line) <= 32 for line in text.splitlines()))
