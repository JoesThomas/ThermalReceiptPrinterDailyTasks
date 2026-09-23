import unittest
from finance_period_helpers import previous_period_label
from savings_runway import savings_totals, calculate_runway
from finance_trends import savings_growth

class FinanceSavingsTests(unittest.TestCase):
    def test_savings_flags(self):
        data = {"accounts":[
            {"name":"Emergency","balance":2500,"include_in_net_cash":True,"include_in_runway":True},
            {"name":"Goal","balance":6000,"include_in_net_cash":True,"include_in_runway":False},
        ]}
        t = savings_totals(data)
        self.assertEqual(t["total"], 8500)
        self.assertEqual(t["runway_accessible"], 2500)

    def test_previous_period(self):
        self.assertEqual(previous_period_label("quarter","2026-Q1"), "2025-Q4")
        self.assertEqual(previous_period_label("year","2026"), "2025")

    def test_growth(self):
        g = savings_growth({"savings_total":9300},{"savings":{"savings_total":8450}})
        self.assertEqual(g["change"], 850)
