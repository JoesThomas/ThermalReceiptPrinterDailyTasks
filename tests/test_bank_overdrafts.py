from receipt.profile import COLUMNS
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from flask import Flask

from finance import bank_accounts, bank_overdrafts
from finance.bank_balance_receipt import bank_balances
from finance.receipt_text import ReceiptText
from web_control.project_tools import register


class BankOverdraftTests(TestCase):
    def test_cash_excludes_credit_once_preserves_pending_holds_and_debt(self):
        cases = [
            (
                {"current": "1.22", "available": "301.22", "overdraft": 300},
                None,
                "1.22",
            ),
            ({"current": 100, "available": 350, "overdraft": 300}, None, "50"),
            ({"current": -50, "available": 250, "overdraft": 300}, None, "-50"),
            ({"current": 100, "available": 400, "overdraft": 300}, "300", "100"),
            ({"current": 100, "available": 400}, "300", "100"),
            ({"current": 100, "available": 100, "overdraft": 300}, "0", "100"),
            ({"current": 100, "overdraft": 300}, None, "100"),
            ({"current": 100, "available": 90}, None, "90"),
            ({"current": 100, "available": 400, "overdraft": None}, None, "100"),
        ]
        for row, override, expected in cases:
            with self.subTest(row=row, override=override):
                original = deepcopy(row)
                self.assertEqual(
                    bank_overdrafts.cash_balance(row, override)[1], D(expected)
                )
                self.assertEqual(row, original)
        for invalid in (-1, "NaN", "bad"):
            with self.assertRaises(ValueError):
                bank_overdrafts.cash_balance(
                    {"current": 100, "available": 400, "overdraft": invalid}
                )

    def test_per_account_adjustment_flows_into_provider_totals_and_receipt(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(bank_accounts, "SELECTION", Path(folder) / "selection.json"),
            patch.object(bank_accounts, "CATALOG", Path(folder) / "catalog.json"),
            patch.object(bank_overdrafts, "FILE", Path(folder) / "overdrafts.json"),
        ):

            def get(token, path):
                if path == "/accounts":
                    return {
                        "results": [
                            {"account_id": token + "-one", "display_name": "Current"},
                            {"account_id": token + "-two", "display_name": "Second"},
                        ]
                    }
                if path == "/cards":
                    return {"results": [{"account_id": "card"}]}
                if path.startswith("/cards/"):
                    return {
                        "results": [
                            {"current": 500, "available": 1500, "credit_limit": 2000}
                        ]
                    }
                return {
                    "results": [
                        {
                            "current": 100,
                            "available": 400,
                            "overdraft": 300,
                            "currency": "GBP",
                        }
                    ]
                }

            collect = lambda: bank_accounts.collect(
                lambda p, _: p, lambda p: "token", get
            )
            collect()
            bank_accounts.choose(
                {"HSBC": ["HSBC-one", "HSBC-two"], "MONZO": ["MONZO-one"]}
            )
            result = collect()
            from datetime import date
            from finance.projection import build_projection

            projection = build_projection(
                result, [], [], [], {"runway_daily_spend": 1}, date(2026, 10, 15)
            )
            self.assertEqual(projection["cash"], D(300))
            self.assertEqual(result["HSBC"]["available"], 200)
            self.assertEqual(result["MONZO"]["available"], 100)
            self.assertEqual(result["AMEX"]["available"], 1500)
            page = ReceiptText()
            bank_balances(page, {"bank_balance_sources": result})
            text = page.render()
            self.assertIn("MONZO total                            £100.00", text)
            self.assertIn("Combined bank balance                  £300.00", text)
            self.assertIn("Overdraft allowance", text)
            self.assertIn("Overdraft excluded from cash above.", text)
            self.assertTrue(all(len(line) <= COLUMNS for line in text.splitlines()))

    def test_web_override_validation_private_storage_clear_and_backup(self):
        from web_control.private_backup import _validate_file

        with (
            TemporaryDirectory() as folder,
            patch.object(bank_accounts, "CATALOG", Path(folder) / "catalog.json"),
            patch.object(bank_accounts, "SELECTION", Path(folder) / "selection.json"),
            patch.object(bank_overdrafts, "FILE", Path(folder) / "overdrafts.json"),
        ):
            from storage import write_json

            write_json(
                bank_accounts.CATALOG,
                {
                    "accounts": [
                        {
                            "provider": "MONZO",
                            "id": "m",
                            "name": "Personal current account",
                        }
                    ]
                },
            )
            app = Flask(
                __name__,
                template_folder=str(
                    Path(__file__).resolve().parents[1] / "web_control/templates"
                ),
            )
            app.secret_key = "test"
            register(app, lambda fn: fn)
            client = app.test_client()
            self.assertEqual(
                client.post(
                    "/finance/accounts/overdrafts", data={"overdraft:MONZO:m": "300"}
                ).status_code,
                302,
            )
            self.assertEqual(bank_overdrafts.load(), {"MONZO": {"m": "300"}})
            with patch(
                "web_control.project_tools.render_template", return_value="accounts"
            ) as render:
                self.assertEqual(client.get("/finance/accounts").status_code, 200)
                self.assertEqual(
                    render.call_args.kwargs["accounts"][0]["overdraft_override"], "300"
                )
            self.assertEqual(bank_overdrafts.FILE.stat().st_mode & 0o777, 0o600)
            original = bank_overdrafts.FILE.read_bytes()
            for value in ("-1", "NaN", "Infinity", "10000001", "not money"):
                client.post(
                    "/finance/accounts/overdrafts", data={"overdraft:MONZO:m": value}
                )
                self.assertEqual(bank_overdrafts.FILE.read_bytes(), original)
            _validate_file("bank_overdrafts.json", {"MONZO": {"m": "300"}})
            with self.assertRaises(ValueError):
                _validate_file("bank_overdrafts.json", {"MONZO": {"m": "-1"}})
            client.post("/finance/accounts/overdrafts", data={"overdraft:MONZO:m": ""})
            self.assertEqual(bank_overdrafts.load(), {"MONZO": {}})
            with self.assertRaises(ValueError):
                bank_overdrafts.save({"MONZO": {"missing": "300"}})
