from receipt.profile import COLUMNS
from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from flask import Flask
from finance.money import format_pounds
from finance.scenario_presets import inputs as saved_inputs
from finance.test_receipt import build, receipt, validate
from web_control.test_finance_tools import register

TODAY = date(2026, 10, 15)


def source():
    return dict(
        valid=True,
        cash=D(2500),
        buffer=D(1000),
        daily=D(5),
        warnings=[],
        primary_bank="HSBC",
        amex=dict(balance=D(1000), full_reserved=False),
        events=[
            dict(date=date(2026, 10, 25), name="Amex payment", amount=D(50)),
            dict(
                date=date(2026, 10, 25),
                name="Linked regular savings payment",
                amount=D(25),
                savings_account="pot",
            ),
        ],
        savings_accounts=[
            dict(
                id="pot",
                name="Example savings",
                label="Holiday pot",
                kind="savings",
                type="savings",
                balance=D(500),
                target=D(5000),
                share=D(100),
                interest_rate=D("3.5"),
                isa_contributions=None,
                date=str(TODAY),
            )
        ],
    )


def values(**changes):
    return dict(
        dict(
            start=str(TODAY),
            months="3",
            salary="3000",
            strategy="amex_first",
            save_all="on",
            use_saved_accounts="on",
            monzo_target="500",
            monzo_balance="200",
            savings_goal="10000",
        ),
        **changes,
    )


class CompactFinanceTests(TestCase):
    def test_connected_accounts_and_totals_in_both_layouts_without_changing_plan(self):
        base = source()
        base["monzo_balance"] = D(400)
        base["bank_balance_sources"] = {
            "HSBC": {
                "available": D(2100),
                "accounts": [
                    {"name": "Current account", "available": D(2000)},
                    {"name": "Second current account", "available": D(100)},
                ],
                "scope": "Selected accounts",
                "checked_at": "2026-10-15T17:00:00+00:00",
            },
            "MONZO": {
                "available": D(400),
                "accounts": [
                    {"name": "Personal current account", "available": D(400)},
                ],
                "scope": "First account (default)",
            },
        }
        result = build(base, values(monzo_balance=""), TODAY)
        original = deepcopy(result)
        for detail in ("compact", "detailed"):
            text = receipt(result, TODAY, detail=detail)
            section = text.split("CONNECTED BANK BALANCES")[1].split(
                "Combined bank balance"
            )[0]
            for label in (
                "HSBC - Current account",
                "HSBC - Second current account",
                "MONZO - Personal current account",
                "HSBC total",
                "MONZO total",
            ):
                self.assertIn(label, section)
            self.assertIn("£2,100.00", section)
            self.assertIn("£400.00", section)
            self.assertIn("MONZO: first account default; check", section)
            self.assertIn("Combined bank balance                  £2,500.00", text)
            self.assertIn("Checked: 15 Oct 2026, 18:00 BST", text)
            self.assertNotIn("Starting Monzo override", text)
            self.assertTrue(all(len(line) <= COLUMNS for line in text.splitlines()))
        self.assertEqual(original, result)
        overridden = build(base, values(), TODAY)
        text = receipt(overridden, TODAY, detail="compact")
        self.assertIn("Starting Monzo override                  £200.00", text)
        self.assertIn("combined bank cash unchanged", " ".join(text.split()))

    def test_collection_preserves_selected_balance_sources_and_manual_override(self):
        from web_control.test_finance_tools import collect

        snapshot = {
            "data": [[], None, None, None, {"bank_data_status": "complete"}],
            "balances": {
                "HSBC": {
                    "available": 2100,
                    "accounts": [{"name": "Current", "available": 2100}],
                },
                "MONZO": {
                    "available": 400,
                    "accounts": [{"name": "Personal", "available": 400}],
                },
            },
        }
        original = deepcopy(snapshot)
        local = {
            "settings": {},
            "subscriptions": {"monthly": [], "yearly": []},
            "accounts": [],
        }
        import services

        pipeline = Mock(
            build_subscription_status=Mock(return_value={"monthly": [], "yearly": []})
        )
        with (
            patch.object(services, "live_pipeline", pipeline, create=True),
            patch(
                "finance.projection.build_projection",
                side_effect=lambda *a, **kw: source(),
            ),
            patch("finance.salary_plan.reserves", return_value={}),
        ):
            connected = collect({}, TODAY, shared_snapshot=snapshot, local=local)
            manual = collect(
                {"opening_cash": "1200"}, TODAY, shared_snapshot=snapshot, local=local
            )
            offline = collect(
                {"opening_cash": "1200", "daily_spend": "10"}, TODAY, local=local
            )
        self.assertEqual(connected["bank_balance_sources"], snapshot["balances"])
        self.assertEqual(connected["monzo_balance"], D(400))
        self.assertFalse(connected["bank_cash_manual"])
        self.assertEqual(manual["bank_balance_sources"], snapshot["balances"])
        self.assertTrue(manual["bank_cash_manual"])
        self.assertEqual(offline["bank_balance_sources"], {})
        self.assertTrue(offline["bank_cash_manual"])
        self.assertEqual(snapshot, original)

    def test_manual_balances_are_labelled_and_sum_to_starting_cash(self):
        base = source()
        base.update(bank_balance_sources={}, bank_cash_manual=True)
        result = build(base, values(), TODAY)
        for detail in ("compact", "detailed"):
            text = receipt(result, TODAY, detail=detail)
            self.assertNotIn("CONNECTED BANK BALANCES", text)
            self.assertIn("HSBC (scenario)                        £2,300.00", text)
            self.assertIn("Monzo (scenario)                         £200.00", text)
            self.assertIn("Combined bank cash used                £2,500.00", text)
            self.assertIn("Manual starting cash", text)

    def test_compact_receipt_orders_actions_before_outcomes_and_keeps_money_correct(
        self,
    ):
        result = build(source(), values(), TODAY)
        original = deepcopy(result)
        short = receipt(result, TODAY, detail="compact")
        full = receipt(result, TODAY, detail="detailed")
        headings = [
            "WHAT TO MOVE THIS PAYDAY",
            "WHAT TO KEEP",
            "BALANCES AT FORECAST END",
            "PROGRESS TOWARDS GOALS",
            "WILL THIS COVER YOUR SPENDING?",
        ]
        positions = [short.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(all(len(line) <= COLUMNS for line in short.splitlines()))
        self.assertLess(len(short), len(full))
        self.assertIn(format_pounds(result["forecast"]["payments"][0]["extra"]), short)
        self.assertIn(
            format_pounds(result["account_plan"]["accounts"][0]["projected"]), short
        )
        self.assertIn("Interest assumption: 3.50% AER", short)
        self.assertIn("HOLIDAY POT", short)
        self.assertNotIn("Linked regular savings payment", short)
        self.assertIn("do not resend", short)
        self.assertIn("Monzo top-up (from reserves)", short)
        self.assertEqual(result, original)
        self.assertEqual(receipt(result, TODAY), full)

    def test_compact_retains_shortfall_and_unknown_balance_warnings(self):
        base = source()
        base["warnings"] = ["Manual estimate: confirm balances."]
        base["amex"]["balance"] = None
        base["cash"] = D(1100)
        result = build(base, values(salary="0"), TODAY)
        text = receipt(result, TODAY, detail="compact")
        self.assertIn("FUNDING WARNING", text)
        self.assertIn("Reserves breached:", text)
        self.assertIn("Amex balance owed: unavailable", text)
        self.assertIn("Manual estimate: confirm balances.", text)

    def test_receipt_detail_is_validated_and_saved_with_scenario_inputs(self):
        self.assertEqual(
            saved_inputs(values(receipt_detail="detailed"))["receipt_detail"],
            "detailed",
        )
        with self.assertRaises(ValueError):
            validate(values(receipt_detail="invalid"), TODAY)
        with self.assertRaises(ValueError):
            receipt(build(source(), values(), TODAY), TODAY, detail="invalid")

    def test_web_generation_defaults_to_compact_and_keeps_explicit_detailed(self):
        app = Flask(__name__)
        app.secret_key = "test"
        start = Mock(return_value=(True, ""))
        register(app, lambda f: f, start)
        with (
            TemporaryDirectory() as folder,
            patch("receipt.archive.DIRECTORY", Path(folder)),
            patch("web_control.test_finance_tools.uk_today", return_value=TODAY),
            patch(
                "web_control.test_finance_tools.collect",
                side_effect=lambda *a, **k: source(),
            ),
        ):
            client = app.test_client()
            for mode in [None, "detailed"]:
                params = values()
                if mode:
                    params["receipt_detail"] = mode
                response = client.post("/finance/test/generate", data=params)
                self.assertEqual(response.status_code, 302)
                with client.session_transaction() as session:
                    identifier = session["test_finance_receipt"]
                from receipt.archive import load

                text = load(identifier)["pages"]["finance"]
                self.assertIn(
                    "WHAT TO MOVE THIS PAYDAY"
                    if mode is None
                    else "PAY PERIOD ALLOCATION",
                    text,
                )
            start.assert_not_called()

    def test_funded_transfer_notes_fit_a_short_block_without_repeating_amounts(self):
        base = source()
        base["cash"] = D(5000)
        base["reserve_details"] = dict(
            target=D(500), held=D(200), gap=D(300), tax_reserve=D(0), date=TODAY
        )
        base["savings_accounts"].append(
            dict(
                id="cash",
                name="Cash",
                kind="savings",
                type="savings",
                balance=D(200),
                target=D(500),
                share=D(0),
                date=str(TODAY),
                isa_contributions=None,
            )
        )
        result = build(base, values(invest_spare_cash="on"), TODAY)
        text = receipt(result, TODAY, detail="compact")
        block = text.split("WHAT TO MOVE THIS PAYDAY")[1].split("WHAT TO KEEP")[0]
        lines = [line for line in block.splitlines() if line and set(line) != {"-"}]
        self.assertLessEqual(len(lines), 9)
        self.assertEqual(block.count("Top-ups use reserves, not extra income."), 1)
        for label in [
            "Cash top-up (from reserves)",
            "Monzo top-up (from reserves)",
            "Spare cash (included above)",
            "Scheduled savings - do not resend",
        ]:
            matching = [line for line in lines if line.startswith(label)]
            self.assertEqual(len(matching), 1)
            self.assertIn("£", matching[0])
        self.assertNotIn("Already included in the transfers above", block)
        self.assertTrue(all(len(line) <= COLUMNS for line in lines))
