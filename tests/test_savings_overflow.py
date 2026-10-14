from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase

from finance.test_receipt import build, receipt

TODAY = date(2026, 10, 14)


def account(name, balance, target, kind="savings", share="50"):
    return dict(
        id=name,
        name=name,
        kind="savings",
        type=kind,
        balance=D(balance) if balance is not None else None,
        date=str(TODAY),
        target=D(target) if target is not None else None,
        share=D(share),
        isa_contributions=None,
        balance_limit=D(target) if target is not None else None,
    )


def base(accounts, cash="0", buffer="0", debt="0"):
    return dict(
        valid=True,
        cash=D(cash),
        buffer=D(buffer),
        daily=D(0),
        warnings=[],
        events=[],
        amex=dict(balance=D(debt), full_reserved=False, apr=D(0)),
        savings_accounts=accounts,
        primary_bank="HSBC",
    )


def values(**changes):
    return dict(
        dict(
            salary="100",
            start=str(TODAY),
            months="1",
            save_all="on",
            use_saved_accounts="on",
            equal_savings="on",
            strategy="amex_first",
        ),
        **changes,
    )


class SavingsOverflowTests(TestCase):
    def test_bonds_hard_cap_redistributes_to_other_goal_and_conserves_money(self):
        source = base(
            [
                account("NS and I", "49990", "60000", "premium_bonds"),
                account("Hargreaves Lansdown", "0", "1000"),
            ]
        )
        before = deepcopy(source)
        result = build(source, values(), TODAY)
        rows = result["account_plan"]["accounts"]
        self.assertEqual([row["projected"] for row in rows], [D(50000), D(90)])
        self.assertEqual(result["forecast"]["savings_total"], 100)
        self.assertEqual(result["forecast"]["unallocated_savings"], 0)
        self.assertEqual(source, before)

    def test_full_goals_leave_income_and_spare_cash_in_bank_every_month(self):
        source = base(
            [
                account("NS and I", "50000", "50000", "premium_bonds"),
                account("HL", "100", "100"),
            ],
            "2000",
            "1000",
        )
        result = build(source, values(months="3", invest_spare_cash="on"), TODAY)
        self.assertEqual(result["forecast"]["savings_total"], 0)
        self.assertEqual(result["forecast"]["end_cash"], 1300)
        self.assertEqual(result["forecast"]["cash_invested_total"], 0)
        self.assertEqual(result["forecast"]["unallocated_savings"], 0)
        self.assertTrue(
            all(row["savings"] == 0 for row in result["forecast"]["payments"])
        )

    def test_missing_balance_share_is_not_applied_twice_or_removed_from_cash(self):
        source = base([account("Known", "0", "1000"), account("Unknown", None, "1000")])
        result = build(source, values(equal_savings="", months="3"), TODAY)
        self.assertEqual(result["account_plan"]["accounts"][0]["added"], 150)
        self.assertEqual(result["forecast"]["savings_total"], 150)
        self.assertEqual(result["forecast"]["end_cash"], 150)
        self.assertEqual(result["forecast"]["unallocated_savings"], 0)

    def test_scheduled_bond_payments_obey_cap_and_do_not_use_same_room_twice(self):
        source = base(
            [
                account("NS and I", "49980", "50000", "premium_bonds"),
                account("HL", "0", "10000"),
            ]
        )
        source["events"] = [
            dict(
                name="NS and I",
                date=date(2026, 10, 20),
                amount=D(25),
                savings_account="NS and I",
            )
        ]
        result = build(source, values(salary="1000"), TODAY)
        self.assertEqual(result["account_plan"]["accounts"][0]["projected"], 50000)
        self.assertEqual(result["forecast"]["automatic_total"], 20)
        self.assertEqual(result["account_plan"]["accounts"][1]["added"], 980)
        self.assertEqual(result["forecast"]["end_cash"], 0)

    def test_no_salary_does_not_invest_spare_bank_cash(self):
        result = build(
            base([account("HL", "0", "10000")], "3000", "1000"),
            values(salary="0", invest_spare_cash="on"),
            TODAY,
        )
        self.assertEqual(result["forecast"]["savings_total"], 0)
        self.assertEqual(result["forecast"]["end_cash"], 2000)

    def test_savings_first_uses_released_capacity_for_debt_before_retaining_cash(self):
        result = build(
            base([account("HL", "0", "10")], debt="50"),
            values(strategy="savings_first"),
            TODAY,
        )
        self.assertEqual(result["forecast"]["payments"][0]["extra"], 50)
        self.assertEqual(result["forecast"]["savings_total"], 10)
        self.assertEqual(result["forecast"]["end_cash"], 40)

    def test_monzo_reserve_and_end_summary_do_not_duplicate_bank_money(self):
        source = base(
            [
                account("NS and I", "50000", "50000", "premium_bonds"),
                account("Hargreaves Lansdown", "20000", "20000"),
            ],
            "1500",
            "1000",
        )
        result = build(
            source,
            values(salary="1000", monzo_target="500", monzo_balance="200"),
            TODAY,
        )
        self.assertEqual(result["projection"]["buffer"], 1500)
        total = result["forecast"]["end_cash"] + result["projection"]["buffer"]
        self.assertEqual(total, 2500)
        text = receipt(result, TODAY)
        section = text.split("BALANCES AT FORECAST END")[1]
        for label, amount in [
            ("HSBC", "£2,000.00"),
            ("Monzo", "£500.00"),
            ("Amex - balance owed", "£0.00"),
            ("NS and I", "£50,000.00"),
            ("Hargreaves Lansdown", "£20,000.00"),
        ]:
            self.assertIn(label, section)
            self.assertIn(amount, section)
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))

    def test_invalid_monzo_balance_cannot_exceed_combined_starting_cash(self):
        with self.assertRaises(ValueError):
            build(
                base([], "100", "100"),
                values(monzo_target="500", monzo_balance="200"),
                TODAY,
            )

    def test_account_without_a_balance_target_can_receive_bond_overflow(self):
        source = base(
            [
                account("NS and I", "50000", "50000", "premium_bonds"),
                account("HL", "20000", None),
            ]
        )
        result = build(source, values(), TODAY)
        self.assertEqual(result["account_plan"]["accounts"][1]["projected"], 20100)
        self.assertEqual(result["forecast"]["savings_total"], 100)
        self.assertEqual(result["forecast"]["end_cash"], 0)
