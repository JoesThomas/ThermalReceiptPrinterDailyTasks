"""Threshold flags cannot imply arrears, spend credit limits or clear on stale data."""

from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock
from types import SimpleNamespace
import sys
from flask import Flask
from finance import amex_protection as protection
from finance.amex_balance import assess, receipt_status
from finance.receipt_text import ReceiptText
from web_control.amex_balance import register

TODAY = date(2026, 10, 26)


def value(amount="500", **changes):
    v = protection.defaults()
    v["evidence"] = dict(
        current=amount,
        currency="GBP",
        checked_at="2026-10-26T10:00:00+00:00",
        amex_ok=True,
        balances={},
        payments=[],
    )
    v.update(changes)
    return v


class BalanceAlertTests(TestCase):
    def test_any_positive_balance_and_strict_threshold(self):
        for amount, level in [
            ("0", "clear"),
            ("-20", "clear"),
            ("0.01", "outstanding"),
            ("1000", "outstanding"),
            ("1000.01", "high"),
        ]:
            result = assess(value(amount), today=TODAY)
            self.assertEqual(result["level"], level)
            self.assertEqual(result["show"], D(amount) > 0)
            self.assertIn("does not", result["message"])
        self.assertEqual(
            assess(value("501", balance_alert_threshold="500"), today=TODAY)["level"],
            "high",
        )
        self.assertFalse(
            assess(value("3000", balance_alert_enabled=False), today=TODAY)["show"]
        )

    def test_stale_failed_and_missing_data_never_claim_cleared(self):
        for change in [
            dict(checked_at="2026-10-20"),
            dict(refresh_failed=True),
            dict(amex_ok=False),
        ]:
            v = value("0")
            v["evidence"].update(
                change, last_known_current="1500", last_known_checked_at="2026-10-20"
            )
            result = assess(v, today=TODAY)
            self.assertEqual(result["level"], "high")
            self.assertTrue(result["stale"])
            self.assertEqual(result["amount"], 1500)
        v = value(None)
        self.assertEqual(assess(v, today=TODAY)["level"], "unknown")
        v = value("1500")
        v["evidence"]["currency"] = "EUR"
        self.assertIsNone(assess(v, today=TODAY)["amount"])
        self.assertFalse(assess(protection.defaults(), today=TODAY)["show"])

    def test_valid_new_zero_clears_prior_balance_and_simulations_do_not_write(self):
        v = value("0")
        v["evidence"].update(
            last_known_current="1500", last_known_checked_at="2026-10-20"
        )
        self.assertEqual(assess(v, today=TODAY)["level"], "clear")
        with (
            TemporaryDirectory() as folder,
            patch.object(protection, "FILE", Path(folder) / "protection.json"),
        ):
            protection.store().update(lambda x: x.update(v))
            before = protection.store().read()
            page = ReceiptText()
            receipt_status(page, D(1600))
            self.assertIn("ABOVE", page.render())
            self.assertIn("Simulated", page.render())
            self.assertEqual(protection.store().read(), before)
            page = ReceiptText()
            receipt_status(page, None)
            self.assertIn("unavailable", page.render())
            self.assertNotIn("Unavailable outstanding", page.render())

    def test_capture_retains_last_known_balance_on_an_incomplete_refresh(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "protection.json"
            with patch.dict(
                sys.modules,
                {
                    "services.live_pipeline": SimpleNamespace(
                        build_subscription_status=Mock(
                            side_effect=RuntimeError("offline")
                        )
                    )
                },
            ):
                protection.capture(
                    {"AMEX": {"current": 1500}},
                    [],
                    {"bank_data_status": "complete"},
                    path=path,
                    checked_at="2026-10-26T10:00:00+00:00",
                )
                protection.capture(
                    {"AMEX": {"current": None}},
                    [],
                    {"bank_data_status": "unavailable"},
                    path=path,
                    checked_at="2026-10-26T11:00:00+00:00",
                )
            result = assess(protection.store(path).read(), today=TODAY)
            self.assertEqual(result["amount"], 1500)
            self.assertTrue(result["stale"])

    def test_threshold_validation_and_legacy_defaults(self):
        v = protection.defaults()
        v.pop("balance_alert_threshold")
        v.pop("balance_alert_enabled")
        protection.validate(v)
        self.assertEqual(assess(v, today=TODAY)["threshold"], 1000)
        for bad in ["", "0", "-1", "NaN", "Infinity", "10000001"]:
            with self.assertRaises(ValueError):
                protection.validate(value(balance_alert_threshold=bad))

    def test_settings_form_changes_only_balance_alert_options(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(protection, "FILE", Path(folder) / "protection.json"),
        ):
            original = value("1500")
            protection.store().update(lambda x: x.update(original))
            app = Flask(__name__)
            app.secret_key = "test"
            app.add_url_rule(
                "/finance-review", endpoint="finance_review", view_func=lambda: "ok"
            )
            register(app, lambda f: f)
            response = app.test_client().post(
                "/finance/amex-balance/settings",
                data={"enabled": "on", "threshold": "750"},
            )
            self.assertEqual(response.status_code, 302)
            after = protection.store().read()
            self.assertEqual(after["balance_alert_threshold"], "750")
            self.assertEqual(after["evidence"], original["evidence"])
            self.assertEqual(after["manual_statement"], original["manual_statement"])
