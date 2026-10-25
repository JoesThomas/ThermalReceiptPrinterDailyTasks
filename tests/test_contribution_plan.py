from receipt.profile import COLUMNS
from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from unittest.mock import patch
from finance.scenario_plan import build
from finance.contribution_plan import contribution_plan
from finance.test_scenarios import compare
from finance.test_receipt import receipt
from finance.savings_targets import link_regular_savings

TODAY = date(2026, 10, 11)


def source():
    return {
        "valid": True,
        "cash": D(4000),
        "buffer": D(1000),
        "daily": D(0),
        "warnings": [],
        "amex": {"balance": D(0), "apr": D(0)},
        "events": [
            {
                "name": "HLAM Regular Saving",
                "amount": D(25),
                "date": date(2026, month, 25),
            }
            for month in (10, 11, 12)
        ],
        "savings_accounts": [
            {
                "id": "hl",
                "name": "Hargreaves Lansdown ISA",
                "kind": "investment",
                "type": "stocks_isa",
                "balance": D(0),
                "target": D(10000),
                "share": D(100),
                "date": str(TODAY),
                "isa_contributions": D(0),
            }
        ],
    }


def values(**changes):
    return dict(
        {
            "salary": "100",
            "start": str(TODAY),
            "months": "3",
            "save_all": "on",
            "invest_spare_cash": "on",
            "use_saved_accounts": "on",
            "equal_savings": "on",
            "strategy": "amex_first",
        },
        **changes,
    )


class ContributionPlanTests(TestCase):
    def test_suggestion_excludes_spare_bank_cash_and_counts_scheduled_once(self):
        base = source()
        original = deepcopy(base)
        current = build(base, values(), TODAY)
        plan = contribution_plan(base, current, TODAY)
        self.assertEqual(plan["scheduled_this_period"], "£25.00")
        self.assertEqual(plan["income_extra_this_period"], "£75.00")
        self.assertEqual(plan["one_off_this_period"], "£3,000.00")
        self.assertEqual(plan["total_this_period"], "£3,100.00")
        self.assertEqual(plan["suggested"], "£100.00")
        self.assertEqual(plan["minimum_bank"], "£1,000.00")
        self.assertEqual(base, original)
        current["contribution"] = plan
        text = receipt(current, TODAY)
        self.assertIn("HARGREAVES LANSDOWN PLAN", text)
        self.assertTrue(all(len(line) <= COLUMNS for line in text.splitlines()))

    def test_explicit_destination_disambiguates_two_isas(self):
        base = source()
        base["savings_accounts"].append(
            dict(
                base["savings_accounts"][0],
                id="hl2",
                name="Hargreaves Lansdown second ISA",
            )
        )
        ambiguous = contribution_plan(base, build(base, values(), TODAY), TODAY)
        self.assertFalse(ambiguous["available"])
        settings = values(payment_account_hlamregularsaving="hl2", hl_account="hl2")
        current = build(base, settings, TODAY)
        self.assertTrue(
            all(event["savings_account"] == "hl2" for event in current["bills"])
        )
        plan = contribution_plan(base, current, TODAY)
        self.assertEqual(plan["account_id"], "hl2")
        self.assertEqual(current["account_plan"]["accounts"][0]["automatic_added"], 0)
        self.assertEqual(current["account_plan"]["accounts"][1]["automatic_added"], 75)

    def test_mapping_uses_ids_and_never_credits_a_scenario_expense(self):
        events = [
            {"name": "HLAM Regular Saving", "amount": D(25)},
            {"name": "HLAM Regular Saving", "amount": D(50), "scenario_expense": True},
        ]
        link_regular_savings(
            events, source()["savings_accounts"], {"hlamregularsaving": "hl"}
        )
        self.assertEqual(events[0]["savings_account"], "hl")
        self.assertNotIn("savings_account", events[1])
        with self.assertRaises(ValueError):
            link_regular_savings(
                events, source()["savings_accounts"], {"hlamregularsaving": "deleted"}
            )

    def test_no_salary_does_not_raise_existing_payment(self):
        base = source()
        settings = values(salary="0", hl_monthly="100")
        current = build(base, settings, TODAY)
        plan = contribution_plan(base, current, TODAY)
        self.assertEqual(plan["suggested"], "£25.00")
        self.assertEqual([p["scheduled"] for p in plan["periods"]], ["£25.00"] * 3)
        self.assertEqual(plan["one_off_this_period"], "£0.00")

    def test_amex_first_waits_for_debt_clearance(self):
        base = source()
        base["cash"] = D(1000)
        base["amex"]["balance"] = D(100)
        settings = values(hl_monthly="100")
        plan = contribution_plan(base, build(base, settings, TODAY), TODAY)
        self.assertEqual(
            [p["scheduled"] for p in plan["periods"]], ["£25.00", "£75.00", "£100.00"]
        )
        self.assertEqual(plan["amex_keep"], plan["amex_proposed"])
        self.assertTrue(plan["reserves_hold"])

    def test_increase_is_capped_by_income_and_reserves(self):
        base = source()
        base["daily"] = D(1)
        settings = values(hl_monthly="10000")
        plan = contribution_plan(base, build(base, settings, TODAY), TODAY)
        self.assertEqual(
            [p["scheduled"] for p in plan["periods"]], ["£69.00", "£70.00", "£69.00"]
        )
        self.assertTrue(plan["reserves_hold"])
        self.assertEqual(plan["minimum_bank"], "£1,000.00")

    def test_skipped_salary_keeps_original_scheduled_payment(self):
        settings = values(hl_monthly="100", missed_salary_dates="2026-11-11")
        base = source()
        plan = contribution_plan(base, build(base, settings, TODAY), TODAY)
        self.assertEqual(
            [p["scheduled"] for p in plan["periods"]], ["£100.00", "£25.00", "£75.00"]
        )

    def test_compare_zero_spending_change_reuses_current_case(self):
        base = source()
        settings = values(comparison_spend="0")
        current = build(base, settings, TODAY)
        with patch(
            "finance.test_scenarios.build_validated",
            wraps=__import__(
                "finance.scenario_plan", fromlist=["build_validated"]
            ).build_validated,
        ) as calculate:
            compare(base, settings, TODAY, current=current)
        # Only sensitivity and the new missed-salary case need calculation.
        self.assertEqual(calculate.call_count, 2)

    def test_maximum_horizon_does_not_repeat_extension(self):
        base = source()
        settings = values(months="60", start=str(TODAY))
        base["savings_accounts"][0]["target"] = D(100000)
        from finance.test_forecast import simulate

        with patch("finance.scenario_plan.simulate", wraps=simulate) as calculate:
            build(base, settings, TODAY)
        self.assertEqual(calculate.call_count, 1)

    def test_two_linked_hl_accounts_keep_distinct_regular_amounts(self):
        base = source()
        base["savings_accounts"].append(
            dict(
                base["savings_accounts"][0],
                id="hl2",
                name="Hargreaves Lansdown second ISA",
            )
        )
        for event in base["events"]:
            event["savings_account"] = "hl"
        base["events"] += [
            dict(
                event,
                name="Hargreaves Lansdown second payment",
                savings_account="hl2",
                amount=D(50),
            )
            for event in list(base["events"])
        ]
        settings = values(hl_account="hl", hl_monthly="50")
        plan = contribution_plan(base, build(base, settings, TODAY), TODAY)
        self.assertEqual(plan["existing"], "£25.00")
        self.assertEqual(plan["scheduled_this_period"], "£25.00")
        self.assertEqual(
            [period["scheduled"] for period in plan["periods"]], ["£50.00"] * 3
        )
