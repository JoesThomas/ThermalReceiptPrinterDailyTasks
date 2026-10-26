"""Monthly long-term conservation, limits, access dates and resilience."""

from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from finance.long_range.config import defaults, account, validate
from finance.long_range.engine import run
from finance.long_range.report import equation, compare, receipt
from finance.long_range import store as records

TODAY = date(2026, 11, 1)


def plan(**changes):
    v = defaults(TODAY)
    v.update(years="2", salary="3000", bills="1000", spending="700")
    v.update(changes)
    v["accounts"][0]["balance"] = "1000"
    return v


def event(kind, amount, on="2027-01-01", account_id="", repeat="0"):
    return dict(
        name="Planned change",
        kind=kind,
        amount=amount,
        date=on,
        account=account_id,
        repeat=repeat,
    )


class LongRangeTests(TestCase):
    def assert_ledger(self, result):
        for point in result["points"]:
            for row in point["accounts"].values():
                self.assertAlmostEqual(equation(row), row["closing"], places=6)

    def test_each_month_equation_and_net_worth_conserve_all_flows(self):
        v = plan()
        v["accounts"] += [
            account(
                "Stock",
                "investment",
                balance="1000",
                low="-5",
                expected="5",
                high="8",
                fee="1",
                tax="20",
                yield_rate="2",
                payout="bank",
            ),
            account(
                "Premium",
                "premium_bonds",
                balance="49990",
                low="0",
                expected="3",
                high="5",
            ),
            account("Amex", "debt", balance="900", monthly="50", apr="20", early=True),
        ]
        before = deepcopy(v)
        r = run(v)
        self.assert_ledger(r)
        self.assertEqual(v, before)
        self.assertEqual(r["final"]["debts"], 0)
        self.assertGreater(r["final"]["payout_cash"], 0)
        self.assertGreaterEqual(r["final"]["bank"], 500)
        self.assertTrue(
            all(
                p["accounts"][v["accounts"][2]["id"]]["closing"] <= 50000
                for p in r["points"]
            )
        )

    def test_goal_does_not_stop_contributions_without_explicit_limit(self):
        v = plan()
        a = account("Pot", "savings", target="100")
        v["accounts"].append(a)
        self.assertGreater(run(v)["final"]["accounts"][a["id"]]["closing"], 100)
        a["stop"] = True
        self.assertEqual(run(v)["final"]["accounts"][a["id"]]["closing"], 100)
        a["stop"] = False
        a["limit"] = "200"
        self.assertEqual(run(v)["final"]["accounts"][a["id"]]["closing"], 200)

    def test_isa_shared_headroom_and_overflow_to_ordinary_savings(self):
        v = plan(isa_allowance="100", cash_isa_limit="50")
        isa = account("ISA", "cash_isa")
        pot = account("Pot")
        v["accounts"] += [isa, pot]
        r = run(v)
        self.assertEqual(r["points"][0]["accounts"][isa["id"]]["closing"], 50)
        self.assertGreater(r["points"][0]["accounts"][pot["id"]]["closing"], 1000)
        # April month-end allocations belong to the new tax year.
        self.assertEqual(r["points"][5]["accounts"][isa["id"]]["closing"], 100)

    def test_pension_access_and_taxed_withdrawal_are_explicit(self):
        v = plan(salary="0", bills="0", spending="0")
        a = account(
            "Pension", "pension", balance="10000", unlock="2027-01-01", tax="20"
        )
        v["accounts"].append(a)
        v["events"] = [
            event("withdraw", "1000", "2026-12-01", a["id"]),
            event("withdraw", "1000", "2027-01-01", a["id"]),
        ]
        r = run(v)
        self.assert_ledger(r)
        self.assertEqual(r["points"][1]["locked"], 10000)
        self.assertEqual(r["points"][2]["locked"], 0)
        self.assertEqual(r["points"][2]["accounts"][a["id"]]["closing"], 9000)
        self.assertEqual(r["points"][2]["bank"], 1800)

    def test_future_prizes_and_market_payouts_do_not_fund_bills(self):
        v = plan(salary="0", bills="100", spending="0")
        a = account(
            "Stocks",
            "investment",
            balance="100000",
            low="5",
            expected="10",
            high="20",
            yield_rate="5",
            payout="bank",
        )
        v["accounts"].append(a)
        r = run(v)
        self.assertGreater(r["final"]["payout_cash"], 0)
        self.assertIsNotNone(r["first_breach"])
        self.assertEqual(r["final"]["bank"], D(1000) - 24 * 100)
        self.assert_ledger(r)

    def test_premium_bond_purchase_waits_and_reinvested_prizes_cap(self):
        v = plan()
        a = account("Premium", "premium_bonds", expected="12", high="12")
        v["accounts"].append(a)
        r = run(v)
        self.assertEqual(r["points"][0]["accounts"][a["id"]]["prizes"], 0)
        self.assertEqual(r["points"][1]["accounts"][a["id"]]["prizes"], 0)
        self.assertGreater(r["points"][2]["accounts"][a["id"]]["prizes"], 0)
        self.assert_ledger(r)

    def test_life_changes_and_repeat_costs_change_later_cashflow(self):
        v = plan()
        v["events"] = [
            event("salary", "0"),
            event("income", "100", "2027-02-01"),
            event("cost", "50", "2027-02-01", repeat="12"),
        ]
        r = run(v)
        self.assertEqual(r["points"][2]["income"], 0)
        self.assertEqual(r["points"][3]["income"], 100)
        self.assertGreater(r["points"][3]["spending"], r["points"][2]["spending"])
        self.assertGreater(r["points"][15]["spending"], r["points"][14]["spending"])

    def test_missing_and_late_salary_reduce_allocations_and_expose_floor(self):
        v = plan()
        a = account("Invest", "investment")
        v["accounts"].append(a)
        normal = run(v)
        missed = run(v, missed_salary=True)
        late = run(v, late_salary=True)
        self.assert_ledger(missed)
        self.assert_ledger(late)
        self.assertEqual(missed["points"][0]["accounts"][a["id"]]["transfers_in"], 0)
        self.assertIsNotNone(missed["first_breach"])
        self.assertGreater(normal["final"]["net_worth"], missed["final"]["net_worth"])
        self.assertAlmostEqual(
            normal["final"]["net_worth"], late["final"]["net_worth"], places=6
        )

    def test_inflation_goal_and_reverse_contribution_estimate(self):
        v = plan(salary="0", bills="0", spending="0")
        a = account("Goal pot")
        v["accounts"].append(a)
        v["goals"] = [
            dict(
                name="Future purchase",
                date="2027-10-31",
                amount="1200",
                account=a["id"],
                inflates=False,
            )
        ]
        r = run(v)
        self.assertEqual(r["goals"][0]["extra_monthly"], 100)
        v["goals"][0]["inflates"] = True
        r = run(v)
        self.assertGreater(r["goals"][0]["extra_monthly"], 100)
        self.assertLess(r["final"]["real_worth"], r["final"]["net_worth"])
        a["limit"] = "100"
        self.assertTrue(run(v)["goals"][0]["limit_blocked"])

    def test_cases_actuals_and_receipt_are_explicit(self):
        v = plan()
        a = account(
            "Stocks", "investment", balance="1000", low="-5", expected="3", high="7"
        )
        v["accounts"].append(a)
        observed = dict(
            account=a["id"], date="2026-11-30", balance="1500", note="Extra deposit"
        )
        r = compare(v, [observed])
        self.assertLess(
            r["cases"][0]["final"]["net_worth"], r["cases"][2]["final"]["net_worth"]
        )
        self.assertEqual(len(r["changes"]), 1)
        text = receipt(v, r)
        self.assertIn("ILLUSTRATIVE MONTHLY MODEL", text)
        self.assertTrue(all(len(line) <= 48 for line in text.splitlines()))

    def test_validation_and_private_baselines_are_immutable(self):
        v = plan()
        with (
            TemporaryDirectory() as folder,
            patch.object(records, "FILE", Path(folder) / "plans.json"),
        ):
            first = records.save(v)
            v["salary"] = "5000"
            second = records.save(v)
            self.assertEqual(
                records.store().read()["plans"][first]["config"]["salary"], "3000"
            )
            self.assertNotEqual(first, second)
            records.observe(
                v["accounts"][0]["id"],
                "2026-11-30",
                "1200",
                "Observed",
                date(2026, 12, 1),
            )
            self.assertEqual(len(records.store().read()["observations"]), 1)
        for changes in (dict(years="41"), dict(inflation="NaN"), dict(minimum="-1")):
            bad = plan()
            bad.update(changes)
            with self.assertRaises(ValueError):
                validate(bad)

    def test_partial_calendar_horizon_and_late_first_payment_conserve_income(self):
        v = plan(start="2026-10-26", years="1", salary="1000", bills="0", spending="0")
        a = run(v)
        b = run(v, late_salary=True)
        self.assertEqual(a["final"]["date"], date(2027, 10, 25))
        self.assertEqual(len(a["points"]), 13)
        self.assertAlmostEqual(
            a["final"]["net_worth"], b["final"]["net_worth"], places=6
        )

    def test_debt_goal_means_owed_at_most_target(self):
        v = plan(salary="0", bills="0", spending="0")
        debt = account("Loan", "debt", balance="1200", monthly="50")
        v["accounts"].append(debt)
        v["goals"] = [
            dict(
                name="Clear loan",
                date="2027-10-31",
                amount="0",
                account=debt["id"],
                inflates=False,
            )
        ]
        result = run(v)
        goal = result["goals"][0]
        self.assertEqual(goal["shortfall"], 600)
        self.assertEqual(goal["extra_monthly"], 50)
        self.assertEqual(goal["reached"], date(2028, 10, 31))

    def test_pension_is_not_an_automatic_surplus_destination(self):
        v = plan()
        pension = account("Pension", "pension", balance="1000", unlock="2040-01-01")
        v["accounts"].append(pension)
        self.assertEqual(run(v)["final"]["accounts"][pension["id"]]["closing"], 1000)
        pension["extra"] = True
        self.assertGreater(run(v)["final"]["accounts"][pension["id"]]["closing"], 1000)

    def test_goal_deadline_never_uses_a_later_months_income(self):
        v = plan()
        pot = account("Pot")
        v["accounts"].append(pot)
        v["goals"] = [
            dict(
                name="Early deadline",
                date="2026-11-15",
                amount="100",
                account=pot["id"],
                inflates=False,
            )
        ]
        goal = run(v)["goals"][0]
        self.assertEqual(goal["projected"], 0)
        self.assertTrue(goal["lump_required"])
        self.assertEqual(goal["as_of"], TODAY)

    def test_purchase_events_cannot_bypass_savings_caps(self):
        v = plan()
        premium = account("Premium", "premium_bonds", balance="49999")
        v["accounts"].append(premium)
        v["events"] = [event("asset_purchase", "100", account_id=premium["id"])]
        with self.assertRaises(ValueError):
            run(v)

    def test_long_term_state_is_included_in_validated_private_backup(self):
        from web_control.private_backup import validate as validate_backup
        import json

        with (
            TemporaryDirectory() as folder,
            patch.object(records, "FILE", Path(folder) / "plans.json"),
        ):
            records.save(plan())
            state = records.store().read()
            payload = json.dumps(
                dict(version=1, files={"long_term_plans.json": state})
            ).encode()
            self.assertIn("long_term_plans.json", validate_backup(payload)["files"])
