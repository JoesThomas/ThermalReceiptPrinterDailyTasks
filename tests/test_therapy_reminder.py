"""Calendar-based payment reminders run only before therapy appointments."""
import ast
from datetime import date, datetime, timedelta
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def reminder_function():
    source = ast.parse((ROOT / "services" / "live_pipeline.py").read_text(encoding="utf-8"))
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                    and node.name == "therapy_payment_due")
    namespace = {"date": date, "datetime": datetime, "ZoneInfo": ZoneInfo}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT), "exec"), namespace)
    return namespace["therapy_payment_due"]


class TherapyReminderTests(unittest.TestCase):
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
