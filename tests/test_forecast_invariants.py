"""Scenario-wide accounting properties rather than copies of implementation steps."""

from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from itertools import product
from unittest import TestCase
from finance.test_receipt import build, receipt
from finance.savings_targets import allocate

TODAY = date(2026, 10, 10)


class ForecastInvariantTests(TestCase):
    def test_cash_debt_and_receipt_reconcile_across_funded_and_unfunded_paths(self):
        for salary, debt, strategy, daily in product(
            ("0", "100", "1000"),
            ("0", "75", "3500"),
            ("amex_first", "savings_first", "split"),
            ("0", "10"),
        ):
            with self.subTest(salary=salary, debt=debt, strategy=strategy, daily=daily):
                base = {
                    "valid": True,
                    "cash": D(1100),
                    "buffer": D(1000),
                    "daily": D(daily),
                    "warnings": [],
                    "amex": {
                        "balance": D(debt),
                        "full_reserved": False,
                        "scheduled": True,
                    },
                    "events": [
                        {
                            "name": "Amex payment",
                            "date": date(2026, m, 25),
                            "amount": D(50),
                        }
                        for m in (10, 11, 12)
                    ],
                }
                before = deepcopy(base)
                values = {
                    "salary": salary,
                    "other_income": "0",
                    "start": str(TODAY),
                    "months": "3",
                    "save_all": "on",
                    "strategy": strategy,
                    "starting_savings": "220",
                    "invest_spare_cash": "on",
                }
                result = build(base, values, TODAY)
                forecast = result["forecast"]
                scheduled = sum(
                    (
                        e["amount"]
                        for e in forecast["events"]
                        if e["name"] == "Amex payment"
                    ),
                    D(0),
                )
                self.assertEqual(
                    forecast["card_end"],
                    D(debt)
                    - scheduled
                    - forecast["extra_total"]
                    + forecast["interest"],
                )
                self.assertGreaterEqual(forecast["card_end"], 0)
                self.assertLessEqual(
                    scheduled + forecast["extra_total"], D(debt) + forecast["interest"]
                )
                self.assertEqual(
                    forecast["savings_end"],
                    D(220)
                    + forecast["savings_total"]
                    + forecast["automatic_total"]
                    + forecast["reserved_total"],
                )
                self.assertEqual(
                    forecast["savings_total"],
                    sum((p["savings"] for p in forecast["payments"]), D(0)),
                )
                spent = sum((e["amount"] for e in forecast["events"]), D(0))
                day_count = (forecast["end"] - TODAY).days + 1
                self.assertEqual(
                    forecast["end_cash"],
                    D(100)
                    + 3 * D(salary)
                    - spent
                    - D(daily) * day_count
                    - forecast["extra_total"]
                    - forecast["savings_total"],
                )
                for period in forecast["payments"]:
                    self.assertGreaterEqual(period["extra"], 0)
                    self.assertGreaterEqual(period["savings"], 0)
                    self.assertLessEqual(
                        period["extra"] + period["savings"],
                        period["budget"] + period["cash_invested"],
                    )
                    if D(salary) == 0:
                        self.assertEqual(period["cash_invested"], 0)
                text = receipt(result, TODAY)
                self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))
                self.assertEqual(base, before)

    def test_equal_account_allocation_conserves_every_penny_and_caps_targets(self):
        for count, budget in product((1, 2, 3, 7), ("0", "0.01", "100", "9999.99")):
            with self.subTest(count=count, budget=budget):
                accounts = [
                    {
                        "id": str(i),
                        "name": f"ISA {i}",
                        "kind": "isa",
                        "type": "stocks_isa",
                        "balance": D(0),
                        "date": str(TODAY),
                        "target": D(100) * (i + 1),
                        "share": D(0),
                        "isa_contributions": D(0),
                    }
                    for i in range(count)
                ]
                before = deepcopy(accounts)
                plan = allocate(
                    accounts, [{"date": TODAY, "savings": D(budget)}], equal=True
                )
                self.assertEqual(
                    sum((a["added"] for a in plan["accounts"]), D(0))
                    + plan["unallocated"],
                    D(budget),
                )
                for account in plan["accounts"]:
                    self.assertGreaterEqual(account["added"], 0)
                    self.assertLessEqual(account["projected"], account["target"])
                self.assertEqual(accounts, before)
