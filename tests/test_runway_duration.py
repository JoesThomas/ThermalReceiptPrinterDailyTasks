import unittest
from datetime import date
from finance.projection import format_runway

class RunwayDurationTests(unittest.TestCase):
    def test_short_and_plural(self):
        for days, expected in [(0,"0 days (0 days)"),(1,"1 day (1 day)"),(7,"1 week (7 days)"),(8,"1 week and 1 day (8 days)")]:
            self.assertEqual(format_runway(days,date(2026,9,30)),expected)

    def test_calendar_months_and_exact_total(self):
        self.assertEqual(format_runway(38,date(2026,9,30)),"1 month, 1 week, and 1 day (38 days)")
        self.assertEqual(format_runway(302,date(2026,9,30)),"9 months, 4 weeks, and 1 day (302 days)")
        self.assertEqual(format_runway(28,date(2027,1,31)),"1 month (28 days)")
        self.assertEqual(format_runway(29,date(2028,1,31)),"1 month (29 days)")
