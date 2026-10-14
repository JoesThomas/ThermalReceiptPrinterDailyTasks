from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from finance import savings_goals as goals
from finance.isa_forecast import allowance_snapshot
from finance.savings_targets import allocate
from finance.test_receipt import build, receipt

TODAY = date(2026, 10, 14)


def account(
    name,
    kind="stocks_isa",
    balance="0",
    target="10000",
    share="100",
    limit=None,
    used="0",
):
    return dict(
        id=name,
        name=name,
        kind="savings" if kind in {"savings", "premium_bonds"} else "investment",
        type=kind,
        balance=D(balance),
        target=D(target) if target is not None else None,
        share=D(share),
        date=str(TODAY),
        isa_contributions=D(used),
        balance_limit=D(limit) if limit is not None else None,
    )


def source(accounts, cash="1000", buffer="1000"):
    return dict(
        valid=True,
        cash=D(cash),
        buffer=D(buffer),
        daily=D(0),
        events=[],
        warnings=[],
        amex=dict(balance=D(0), full_reserved=False),
        savings_accounts=accounts,
        primary_bank="HSBC",
    )


def values(today=TODAY, **changes):
    return dict(
        dict(
            salary="1000",
            start=str(today),
            months="1",
            strategy="amex_first",
            save_all="on",
            use_saved_accounts="on",
            respect_isa_allowance="on",
        ),
        **changes,
    )


class LimitsAndISATests(TestCase):
    def test_reported_surplus_goes_to_hl_after_goal_and_leaves_hsbc_at_1000(self):
        rows = [
            account("NS and I", "premium_bonds", "50000", "50000", "0"),
            account("Hargreaves Lansdown", "stocks_isa", "10150", "10000", "100"),
            account("Cash", "savings", "500", "500", "0"),
        ]
        base = source(rows, "8417.86")
        base["reserve_details"] = dict(target=D(500), held=D(500), gap=D(0), tax_reserve=D(0), date=TODAY)
        result = build(
            base,
            values(
                salary="1",
                invest_spare_cash="on",
                monzo_target="500",
                monzo_balance="500",
            ),
            TODAY,
        )
        self.assertEqual(
            result["account_plan"]["accounts"][1]["projected"], D("17068.86")
        )
        self.assertEqual(result["account_plan"]["accounts"][2]["projected"], 500)
        self.assertEqual(result["forecast"]["end_cash"], 0)
        text = receipt(result, TODAY)
        self.assertNotIn("excludes Monzo", text)
        self.assertIn("£17,068.86", text)

    def test_soft_goal_continues_and_explicit_cap_redirects(self):
        rows = [
            account("ISA", limit="1050"),
            account("Savings", "savings", share="0", target=None),
        ]
        result = build(source(rows), values(salary="2000"), TODAY)
        self.assertEqual(
            [row["projected"] for row in result["account_plan"]["accounts"]],
            [1050, 950],
        )
        self.assertEqual(result["forecast"]["savings_total"], 2000)
        self.assertEqual(result["forecast"]["end_cash"], 0)
        unlimited = account("Unlimited", balance="12000", target="10000")
        plan = allocate([unlimited], [dict(date=TODAY, savings=D(1000))])
        self.assertEqual(plan["accounts"][0]["projected"], 13000)
        self.assertEqual(plan["accounts"][0]["goal_date"], "already")

    def test_shared_allowance_is_one_pool_across_multiple_isas(self):
        rows = [
            account("ISA 1", share="50", used="19000"),
            account("ISA 2", share="50"),
            account("Savings", "savings", share="0", target=None),
        ]
        result = build(source(rows), values(salary="5000"), TODAY)
        self.assertEqual(
            sum(row["added"] for row in result["account_plan"]["accounts"][:2]), 1000
        )
        self.assertEqual(
            [row["added"] for row in result["account_plan"]["accounts"][:2]],
            [500, 500],
        )
        self.assertEqual(result["account_plan"]["accounts"][2]["added"], 4000)
        self.assertEqual(result["forecast"]["end_cash"], 0)
        self.assertEqual(result["account_plan"]["isa_years"][2026]["used"], 20000)

    def test_cash_isa_pool_is_split_fairly_across_cash_accounts(self):
        rows = [
            account("Cash ISA 1", "cash_isa", share="50"),
            account("Cash ISA 2", "cash_isa", share="50"),
            account("Savings", "savings", share="0", target=None),
        ]
        day = date(2027, 4, 6)
        result = build(source(rows), values(start=day.isoformat(), salary="30000"), day)
        self.assertEqual(
            [row["added"] for row in result["account_plan"]["accounts"]],
            [6000, 6000, 18000],
        )

    def test_checkbox_off_removes_annual_constraint_but_keeps_balance_cap(self):
        rows = [
            account("ISA", used="20000", limit="500"),
            account("Savings", "savings", share="0", target=None),
        ]
        result = build(
            source(rows), values(salary="1000", respect_isa_allowance=""), TODAY
        )
        self.assertEqual(result["account_plan"]["accounts"][0]["added"], 500)
        self.assertEqual(result["forecast"]["end_cash"], 500)

    def test_allowance_resets_on_six_april_without_counting_balances(self):
        today = date(2027, 4, 5)
        rows = [
            account("ISA", balance="50000", used="20000"),
            account("Savings", "savings", share="0", target=None),
        ]
        result = build(source(rows), values(today, months="2"), today)
        self.assertEqual(result["account_plan"]["accounts"][0]["added"], 1000)
        self.assertEqual(result["account_plan"]["accounts"][1]["added"], 1000)
        self.assertEqual(result["account_plan"]["isa_years"][2026]["used"], 20000)
        self.assertEqual(result["account_plan"]["isa_years"][2027]["used"], 1000)

    def test_2027_cash_limit_age_band_and_shared_allowance(self):
        today = date(2027, 4, 6)
        for over, expected in [("", 12000), ("on", 20000)]:
            rows = [
                account("Cash ISA", "cash_isa"),
                account("Savings", "savings", share="0", target=None),
            ]
            result = build(
                source(rows), values(today, salary="25000", isa_over_65=over), today
            )
            self.assertEqual(result["account_plan"]["accounts"][0]["added"], expected)
            self.assertEqual(
                result["account_plan"]["accounts"][1]["added"], 25000 - expected
            )
            self.assertEqual(result["forecast"]["end_cash"], 0)

    def test_scheduled_subscriptions_share_allowance_with_extra_and_override(self):
        rows = [
            account("Hargreaves Lansdown", used="19990"),
            account("Savings", "savings", share="0", target=None),
        ]
        base = source(rows)
        base["events"] = [
            dict(name="Hargreaves Lansdown", amount=D(25), date=date(2026, 10, 20))
        ]
        result = build(
            base, values(hl_account="Hargreaves Lansdown", hl_monthly="100"), TODAY
        )
        self.assertEqual(result["account_plan"]["accounts"][0]["added"], 10)
        self.assertEqual(result["account_plan"]["accounts"][1]["added"], 990)
        self.assertEqual(
            result["forecast"]["savings_total"] + result["forecast"]["automatic_total"],
            1000,
        )
        self.assertEqual(result["forecast"]["end_cash"], 0)
        self.assertTrue(result["forecast"]["capped_savings_events"])

    def test_multiple_months_preserve_actual_allocations_when_future_schedule_changes(
        self,
    ):
        rows = [
            account("Hargreaves Lansdown"),
            account("Savings", "savings", share="0", target=None),
        ]
        base = source(rows)
        base["events"] = [
            dict(name="Hargreaves Lansdown", amount=D(25), date=date(2026, month, 20))
            for month in (10, 11, 12)
        ]
        result = build(
            base,
            values(
                salary="15000",
                months="3",
                hl_account="Hargreaves Lansdown",
                hl_monthly="100",
            ),
            TODAY,
        )
        self.assertEqual(result["account_plan"]["accounts"][0]["added"], 20000)
        self.assertEqual(result["account_plan"]["accounts"][1]["added"], 25000)
        self.assertEqual(
            result["forecast"]["savings_total"] + result["forecast"]["automatic_total"],
            45000,
        )
        self.assertEqual(
            sum(row["added"] for row in result["account_plan"]["accounts"]), 45000
        )
        self.assertEqual(result["forecast"]["end_cash"], 0)

    def test_no_ordinary_destination_keeps_overflow_in_bank(self):
        result = build(source([account("ISA", used="20000")]), values(), TODAY)
        self.assertEqual(result["forecast"]["savings_total"], 0)
        self.assertEqual(result["forecast"]["end_cash"], 1000)

    def test_recorded_transfers_and_interest_do_not_consume_shared_allowance(self):
        state = dict(
            accounts={"isa": dict(name="ISA", type="stocks_isa")}, years={}, entries=[]
        )
        for event in (
            "contribution",
            "transfer",
            "interest",
            "withdrawal",
            "replacement",
        ):
            state["entries"].append(
                dict(
                    account="isa",
                    date=str(TODAY),
                    event=event,
                    amount="1000",
                    isa_type="stocks_isa",
                )
            )
        view = allowance_snapshot([account("ISA")], TODAY, state)
        self.assertEqual(view[2026]["used"], 1000)

    def test_limit_settings_preserve_clear_validate_and_backup(self):
        from web_control import private_backup

        with TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "data" / "savings_goals.json"
            with patch.object(goals, "FILE", file):
                goals.account_settings(
                    "New savings", "savings", "savings", "1000", "100", "2000"
                )
                key = goals.identity("New savings", "savings")
                self.assertEqual(
                    goals.load()["accounts"][key]["balance_limit"], "2000.00"
                )
                goals.account_settings(
                    "New savings", "savings", "savings", "1500", "100"
                )
                self.assertEqual(
                    goals.load()["accounts"][key]["balance_limit"], "2000.00"
                )
                before = deepcopy(goals.load())
                for limit in ("-1", "NaN", "10000001"):
                    with self.assertRaises(ValueError):
                        goals.account_settings(
                            "New savings", "savings", "savings", "1000", "100", limit
                        )
                self.assertEqual(goals.load(), before)
                value = private_backup.validate(private_backup.export(root))
                self.assertEqual(
                    value["files"]["savings_goals.json"]["accounts"][key][
                        "balance_limit"
                    ],
                    "2000.00",
                )
                goals.account_settings(
                    "New savings", "savings", "savings", "1500", "100", ""
                )
                self.assertIsNone(goals.load()["accounts"][key]["balance_limit"])
                with self.assertRaises(ValueError):
                    goals.account_settings(
                        "PB", "savings", "premium_bonds", "50000", "0", "50001"
                    )
