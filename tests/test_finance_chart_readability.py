"""Readable axes and monthly ranges use the same underlying cash forecast."""

from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.visuals import line_chart, test_charts
from finance.scenario_plan import build
from test_amex_reserve_priority import base, values, TODAY


class ChartReadabilityTests(TestCase):
    def test_regular_money_ticks_dates_and_raw_values(self):
        start = date(2026, 10, 26)
        end = date(2028, 10, 25)
        model = line_chart(
            "cash",
            "Cash",
            [dict(name="Cash", values=[(start, D("-250")), (end, D("4402.94"))])],
            band=D(500),
        )
        self.assertGreaterEqual(len(model["y_ticks"]), 4)
        self.assertLessEqual(len(model["y_ticks"]), 8)
        self.assertEqual(len(model["x_ticks"]), 5)
        self.assertEqual(model["band_value"], "500")
        self.assertEqual(model["series"][0]["data"][1]["raw"], "4402.94")
        self.assertLessEqual(D(model["axis_low"]), -250)
        self.assertGreaterEqual(D(model["axis_high"]), D("4402.94"))

    def test_long_bank_chart_defaults_to_true_daily_monthly_ranges(self):
        result = build(base(), values(months="12"), TODAY)
        chart = test_charts(result, TODAY, [])["lines"][0]
        self.assertEqual(chart["mode"], "monthly")
        self.assertTrue(chart["range_band"])
        self.assertEqual(chart["alt_model"]["series"][0]["name"], "Selected forecast")
        ranges = result["forecast"]["monthly_ranges"]
        self.assertEqual(
            min(r["low"] for r in ranges), result["forecast"]["minimum_bank"]
        )
        self.assertTrue(all(r["low"] <= r["closing"] <= r["high"] for r in ranges))
        self.assertEqual(
            chart["stats"][0]["value"], f"£{result['forecast']['minimum_bank']:,.2f}"
        )

    def test_short_chart_retains_cash_flow_and_offers_range_view(self):
        result = build(base(), values(months="2"), TODAY)
        chart = test_charts(result, TODAY, [])["lines"][0]
        self.assertEqual(chart["mode"], "cashflow")
        self.assertTrue(chart["alt_model"]["range_band"])
