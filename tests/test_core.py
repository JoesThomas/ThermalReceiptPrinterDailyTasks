import unittest
from datetime import date
from actions.deliveries import compact_delivery
from meals.shopping import choose_pack_size
from meals.inventory import use_first

class CoreTests(unittest.TestCase):
    def test_delivery_today(self):
        carrier, expected = compact_delivery({
            "subject": "Royal Mail parcel out for delivery",
            "status": "out for delivery",
        }, today=date(2026, 9, 23))
        self.assertEqual(carrier, "ROYAL MAIL")
        self.assertEqual(expected, "Expected today")

    def test_delivery_window(self):
        carrier, expected = compact_delivery({
            "subject": "Amazon arriving 13:00-16:00",
        }, today=date(2026, 9, 23))
        self.assertEqual(carrier, "AMAZON")
        self.assertEqual(expected, "Expected 13:00-16:00")

    def test_pack_size(self):
        result = choose_pack_size("basmati rice", 375, 140)
        self.assertEqual(result["need"], 235)
        self.assertEqual(result["buy"], 500)
        self.assertEqual(result["remaining"], 265)

    def test_use_first(self):
        items = [{"name": "spinach", "use_by": "2026-09-25"}]
        result = use_first(items, today=date(2026, 9, 23), days=3)
        self.assertEqual(result[0]["name"], "spinach")

if __name__ == "__main__":
    unittest.main()
