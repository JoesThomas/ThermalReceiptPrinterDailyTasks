"""Calendar-based payment reminders run only before therapy appointments."""
import ast
from datetime import date, datetime, timedelta
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from receipt.therapy_payment import recent_therapy_payment


ROOT = Path(__file__).resolve().parents[1]


def reminder_function():
    source = ast.parse((ROOT / "services" / "live_pipeline.py").read_text(encoding="utf-8"))
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                    and node.name == "therapy_payment_due")
    namespace = {"date": date, "datetime": datetime, "ZoneInfo": ZoneInfo}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT), "exec"), namespace)
    return namespace["therapy_payment_due"]


class TherapyReminderTests(unittest.TestCase):
    def test_recent_outgoing_payment_to_configured_payee_suppresses_reminder(self):
        today = date(2026, 9, 28)
        transactions = [{"timestamp": "2026-09-27T12:00:00Z", "amount": -110,
                         "description": "Example Therapist Payment"}]
        self.assertTrue(recent_therapy_payment(transactions, payee="Example Therapist", today=today))
        self.assertFalse(recent_therapy_payment(transactions, payee="Different Payee", today=today))
        printer_lines = []
        source = ast.parse((ROOT / "services" / "live_pipeline.py").read_text(encoding="utf-8"))
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                        and node.name == "print_google_doc")
        namespace = {"print_line": lambda *args: None,
                     "left": lambda *args: None,
                     "printer_safe_text": str,
                     "print_wrapped": lambda printer, text, width: printer_lines.append(text),
                     "therapy_payment_due": lambda events: True}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT), "exec"), namespace)
        printer = SimpleNamespace(set=lambda **kwargs: None)
        namespace["print_google_doc"](printer, "Pay for therapy.\nRead a book.", [], therapy_paid=True)
        self.assertNotIn("[ ] Pay for therapy", printer_lines)
        self.assertIn("[ ] Read a book", printer_lines)
        namespace["print_google_doc"](printer, "", [], therapy_paid=False)
        self.assertIn("[ ] Pay for therapy", printer_lines)

    def test_old_incoming_and_unrelated_payments_do_not_suppress(self):
        today = date(2026, 9, 28)
        transactions = [
            {"date": "2026-09-25", "amount": -110, "description": "Example Therapist"},
            {"date": "2026-09-27", "amount": 110, "transaction_type": "CREDIT",
             "description": "Example Therapist"},
            {"date": "2026-09-27", "amount": -110, "description": "Different payee"},
            {"date": "2026-09-29", "amount": -110, "description": "Example Therapist"},
        ]
        self.assertFalse(recent_therapy_payment(transactions, payee="Example Therapist", today=today))

    def test_bank_lookup_checks_selected_provider_and_keeps_reminder_on_error(self):
        source = ast.parse((ROOT / "services" / "live_pipeline.py").read_text(encoding="utf-8"))
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                        and node.name == "therapy_paid_recently")
        calls = []
        namespace = {
            "timedelta": timedelta,
            "requests": SimpleNamespace(RequestException=RuntimeError),
            "_initial_truelayer_refresh_token": lambda provider: "refresh",
            "_refresh_truelayer_access_token": lambda provider, token: calls.append(provider) or "access",
            "_truelayer_account_ids": lambda token: ["account"],
            "_truelayer_transactions": lambda *args, **kwargs: [{
                "date": "2026-09-27", "amount": -110,
                "description": "Example Therapist"}],
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT), "exec"), namespace)
        settings = {"therapy_payment": {"provider": "MONZO", "payee": "Example Therapist"}}
        self.assertTrue(namespace["therapy_paid_recently"](settings, date(2026, 9, 28)))
        self.assertEqual(calls, ["MONZO"])
        namespace["_truelayer_account_ids"] = lambda token: (_ for _ in ()).throw(RuntimeError("offline"))
        self.assertFalse(namespace["therapy_paid_recently"](settings, date(2026, 9, 28)))

    def test_only_two_or_three_days_before_therapy(self):
        due = reminder_function()
        today = date(2026, 9, 28)
        for days in (-1, 0, 1, 4):
            with self.subTest(days=days):
                self.assertFalse(due([{"title": "Therapy", "date": today + timedelta(days=days)}], today))
        for days in (2, 3):
            with self.subTest(days=days):
                self.assertTrue(due([{"title": "Therapy", "date": today + timedelta(days=days)}], today))

    def test_ignores_undated_or_unrelated_events(self):
        due = reminder_function()
        today = date(2026, 9, 28)
        self.assertFalse(due([{"title": "Therapy"},
                              {"title": "Dentist", "date": today + timedelta(days=2)}], today))
        self.assertTrue(due([{"title": "Therapy", "date": "2026-09-30"}], today))


if __name__ == "__main__":
    unittest.main()
