from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from finance import savings_goals as goals
from finance.savings_targets import allocate
from finance.test_receipt import build, receipt

TODAY = date(2026, 10, 15)


def account(**changes):
    return dict(
        dict(
            id="pot",
            name="Holiday pot",
            kind="savings",
            type="savings",
            balance=D(1000),
            target=D(1050),
            share=D(100),
            date="2026-01-01",
            interest_rate=D(5),
            rate_date="2026-01-01",
            isa_contributions=None,
        ),
        **changes,
    )


def plan(rows, days=365, periods=(), automatic=(), **changes):
    return allocate(
        rows,
        periods,
        automatic,
        start_date=TODAY,
        end_date=TODAY + timedelta(days=days),
        **changes,
    )


class SavingsInterestTests(TestCase):
    def test_aer_is_annual_effective_growth_and_target_can_be_reached_by_interest(self):
        original = [account()]
        snapshot = deepcopy(original)
        result = plan(original, total_goal=D(1050))
        row = result["accounts"][0]
        self.assertEqual(row["projected"], 1050)
        self.assertEqual(row["estimated_interest"], 50)
        self.assertEqual(row["added"], 0)
        self.assertEqual(row["goal_date"], TODAY + timedelta(days=365))
        self.assertEqual(result["goal_date"], row["goal_date"])
        self.assertEqual(original, snapshot)

    def test_contributions_only_earn_interest_after_their_transfer_date(self):
        row = account(balance=D(0), target=None)
        payment = dict(date=TODAY + timedelta(days=182), savings=D(1000))
        result = plan([row], periods=[payment])["accounts"][0]
        expected = (D(1000) * D("1.05") ** (D(183) / 365)).quantize(D(".01"))
        self.assertEqual(result["projected"], expected)
        self.assertEqual(result["added"], 1000)
        self.assertEqual(result["estimated_interest"], expected - 1000)

    def test_growth_is_independent_of_unrelated_timeline_events(self):
        events = [
            dict(date=TODAY + timedelta(days=i), savings=D(0)) for i in range(1, 365)
        ]
        simple = plan([account()])
        busy = plan([account()], periods=events)
        self.assertEqual(simple["projected_total"], busy["projected_total"])
        self.assertEqual(
            simple["accounts"][0]["goal_date"], busy["accounts"][0]["goal_date"]
        )

    def test_effective_date_is_honoured_and_old_valuation_is_not_backfilled(self):
        row = account(rate_date=(TODAY + timedelta(days=100)).isoformat())
        result = plan([row], days=465)
        self.assertEqual(result["projected_total"], 1050)
        self.assertEqual(
            result["accounts"][0]["goal_date"], TODAY + timedelta(days=465)
        )
        self.assertEqual(plan([row], days=99)["projected_total"], 1000)

    def test_zero_missing_rates_investments_and_physical_cash_do_not_grow(self):
        for changes in [
            dict(interest_rate=None),
            dict(interest_rate=D(0)),
            dict(type="stocks_isa"),
            dict(cash_reserve_limit=D(1000)),
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(plan([account(**changes)])["projected_total"], 1000)

    def test_interest_is_not_an_isa_subscription_or_an_extra_transfer(self):
        limits = {
            2026: dict(
                allowance=D(20000),
                cash_limit=D(20000),
                used=D(20000),
                cash_used=D(20000),
                lifetime_used=D(0),
            ),
            2027: dict(
                allowance=D(20000),
                cash_limit=D(12000),
                used=D(0),
                cash_used=D(0),
                lifetime_used=D(0),
            ),
        }
        result = plan(
            [account(type="cash_isa", balance_limit=D(1000))], isa_limits=limits
        )
        self.assertEqual(result["projected_total"], 1050)
        self.assertEqual(result["isa_years"], limits)
        self.assertEqual(result["accounts"][0]["added"], 0)

    def test_forecast_receipt_totals_and_goal_dates_include_interest(self):
        base = dict(
            valid=True,
            cash=D(1000),
            buffer=D(1000),
            daily=D(0),
            events=[],
            warnings=[],
            amex=dict(balance=D(0), full_reserved=False),
            savings_accounts=[account()],
            primary_bank="HSBC",
        )
        values = dict(
            start=str(TODAY),
            months="13",
            salary="0",
            strategy="amex_first",
            save_all="on",
            use_saved_accounts="on",
            savings_goal="1050",
        )
        result = build(base, values, TODAY)
        self.assertEqual(result["forecast"]["goal_date"], TODAY + timedelta(days=365))
        self.assertEqual(result["forecast"]["end_cash"], 0)
        self.assertEqual(result["forecast"]["savings_total"], 0)
        self.assertEqual(
            result["forecast"]["savings_end"], result["account_plan"]["projected_total"]
        )
        text = receipt(result, TODAY)
        for label in [
            "Interest assumption: 5.00% AER",
            "Estimated interest (before tax)",
            "Estimated savings interest",
            "Projected account balance",
            "Target balance",
            "Projected target date:",
            "Projected goal date:",
        ]:
            self.assertIn(label, text)
        self.assertNotIn("No savings growth or", text)

    def test_rate_persists_and_can_be_cleared_without_changing_balance_or_ledger(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(goals, "FILE", Path(folder) / "goals.json"),
        ):
            goals.account_settings("Holiday pot", "savings", "savings", "2000")
            key = goals.identity("Holiday pot", "savings")
            goals.interest_rate(key, "4.5", str(TODAY))
            goals.account_settings("Holiday pot", "savings", "savings", "2500")
            self.assertEqual(
                D(goals.load()["accounts"][key]["interest_rate"]), D("4.5")
            )
            self.assertEqual(goals.load()["entries"], [])
            for rate in ["-1", "NaN", "Infinity", "101"]:
                with self.assertRaises(ValueError):
                    goals.interest_rate(key, rate, str(TODAY))
            goals.interest_rate(key, "", str(TODAY))
            self.assertIsNone(goals.load()["accounts"][key]["interest_rate"])

    def test_scheduled_payment_cash_flow_matches_capped_interest_bearing_balance(self):
        row = account(
            balance=D(990), balance_limit=D(1000), target=D(1000), interest_rate=D(100)
        )
        base = dict(
            valid=True,
            cash=D(1200),
            buffer=D(1000),
            daily=D(0),
            events=[
                dict(
                    name="Holiday pot",
                    amount=D(100),
                    date=TODAY + timedelta(days=25),
                    savings_account="pot",
                )
            ],
            warnings=[],
            amex=dict(balance=D(0), full_reserved=False),
            savings_accounts=[row],
        )
        result = build(
            base,
            dict(
                start=str(TODAY),
                months="1",
                salary="0",
                strategy="amex_first",
                use_saved_accounts="on",
                save_all="on",
            ),
            TODAY,
        )
        final = result["account_plan"]["accounts"][0]
        self.assertEqual(
            result["forecast"]["automatic_total"], final["automatic_added"]
        )
        self.assertEqual(result["forecast"]["end_cash"] + final["added"], 200)
        self.assertEqual(
            final["projected"],
            row["balance"] + final["added"] + final["estimated_interest"],
        )
