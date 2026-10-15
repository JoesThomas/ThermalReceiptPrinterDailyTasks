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
        self.assertTrue(all(len(line) <= 42 for line in short.splitlines()))
        self.assertLess(len(short), len(full))
        self.assertIn(format_pounds(result["forecast"]["payments"][0]["extra"]), short)
        self.assertIn(
            format_pounds(result["account_plan"]["accounts"][0]["projected"]), short
        )
        self.assertIn("Interest assumption: 3.50% AER", short)
        self.assertIn("HOLIDAY POT", short)
        self.assertNotIn("Linked regular savings payment", short)
        self.assertIn("Do not send again", short)
        self.assertIn("Internal bank transfer", short)
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
