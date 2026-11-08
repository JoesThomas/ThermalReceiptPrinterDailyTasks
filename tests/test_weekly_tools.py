from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from finance import bill_history
from meals import household, use_first
from receipt import quick_note
from storage import write_json


class WeeklyToolsTests(unittest.TestCase):
    def test_quick_note_has_one_checkbox_per_input_line_and_no_control_bytes(self):
        rendered = quick_note.format_note("Buy £5 of milk and bread\n\nCall\x00 garage", True, 18)
        self.assertEqual(rendered.splitlines(), ["[ ] Buy £5 of milk", "    and bread", "", "[ ] Call garage"])
        self.assertEqual(quick_note.format_note("First\nSecond"), "First\nSecond\n")
        with self.assertRaises(ValueError):
            quick_note.format_note("\x00")
        with self.assertRaises(ValueError):
            quick_note.format_note("x\n" * 81)

    def test_print_payload_is_not_retained_after_printer_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            key = quick_note.spool(temp, "Private text\n")
            with patch("receipt.printer.open_printer", side_effect=OSError):
                with self.assertRaises(OSError):
                    quick_note.send(temp, key)
            self.assertFalse(quick_note.path_for(temp, key).exists())

    def test_bill_decision_changes_forecast_only_for_recurring(self):
        for decision, expected in (("one-off", 50), ("recurring", 65)):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "subscriptions.json"
                payment = dict(date="2026-11-06", amount=65, expected=50, decision="pending")
                state = dict(monthly=[dict(name="Energy", amount=50, last_paid=payment["date"],
                                           history=[payment])], yearly=[], instalments=[])
                write_json(target, state)
                key = bill_history.entries(state)[0]["key"]
                bill_history.decide(target, key, decision)
                saved = bill_history.store(target).read()["monthly"][0]
                self.assertEqual(saved["amount"], expected)
                self.assertEqual(saved["history"][0]["amount"], 65)
                self.assertEqual(saved["history"][0]["decision"], decision)
                with self.assertRaises(ValueError):
                    bill_history.decide(target, key, "recurring")

    def test_use_first_excludes_past_fridge_windows_and_changed_recipes(self):
        recipe = {"name": "Rice and beans", "ingredients": ["Rice"], "dietary": {}}
        row = dict(id="test", recipe=recipe["name"], signature=use_first.signature(recipe),
                   location="fridge", portions=2, cooked="2026-11-07", use_by="2026-11-09")
        prefs = {"_household": household.defaults()}
        recipes = {recipe["name"]: recipe}
        with patch("receipt.lifestyle.skip_meal", return_value=False):
            self.assertEqual(use_first.options([row], recipes, prefs, date(2026, 11, 7))[0]["needed"], 1)
            self.assertEqual(use_first.options([row], recipes, prefs, date(2026, 11, 8)), [])
            changed = {recipe["name"]: dict(recipe, ingredients=["Chicken"])}
            self.assertEqual(use_first.options([row], changed, prefs, date(2026, 11, 7)), [])

    def test_weekly_review_flags_shop_timing_and_excludes_outside_week(self):
        from organiser.weekly_review import review
        from unittest.mock import Mock

        day = date(2026, 11, 8)
        events = [dict(date="2026-11-12", all_day=True, title="All-day appointment"),
                  dict(date="2026-11-15", all_day=True, title="Outside window")]
        task = dict(shop_supplier="Butcher", shop_day="2026-11-12", shop_month="2026-11",
                    done=False, title="Visit butcher")
        with patch("organiser.records.store", return_value=Mock(read=lambda: {"items": [], "travel_buffer": 30})), \
             patch("services.vehicle_records.load", return_value={"vehicles": []}), \
             patch("actions.checklists.load", return_value={"items": [task]}), \
             patch("receipt_settings.load_receipt_settings", return_value={"features": {"meals": True}}):
            view = review(day, events, actions_only=True)
        self.assertEqual({r["title"] for r in view["rows"]}, {"All-day appointment", "Visit butcher"})
        self.assertIn("Check timing", view["actions"][0]["title"])
        self.assertEqual(view["actions"][0]["args"]["day"], "2026-11-12")
