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

    def test_years_and_forecast_dates(self):
        from finance.projection import build_projection, payment_schedule
        today = date(2026,9,30)
        self.assertEqual(format_runway(678,today), "1 year, 10 months, 1 week, and 2 days (678 days)")
        result = build_projection({'HSBC':{'available':677},'MONZO':{'available':0}}, [], [], [], {'runway_daily_spend':1}, today)
        self.assertEqual(result['cash_days'],678)
        self.assertEqual(result['cash_run_out_date'], date(2028,8,8))
        unknown = build_projection({}, [], [], [], {'runway_daily_spend':1}, today)
        self.assertIsNone(unknown['cash_run_out_date'])
        long = build_projection({'HSBC':{'available':100000},'MONZO':{'available':0}}, [], [], [], {'runway_daily_spend':1}, today)
        self.assertIsNone(long['cash_run_out_date'])
        events, _, _ = payment_schedule([{'name':'Bill','amount':10,'due_day':15}], [{'name':'Annual','amount':100,'renewal_date':'2026-10-10'}], [], {}, today)
        self.assertTrue(any(e['date'].year == 2030 and e['name'] == 'Bill' for e in events))
        self.assertTrue(any(e['date'].year == 2030 and e['name'] == 'Annual' for e in events))
