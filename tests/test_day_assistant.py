import ast
import os
import tempfile
import textwrap
import traceback
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from actions import checklists, day_assistant as assistant
from receipt.text import printer_safe_text
from receipt_settings import DEFAULT_SETTINGS
from storage import write_json

UK = ZoneInfo("Europe/London")
NOW = datetime(2026, 10, 13, 9, tzinfo=UK)


def task(key, **changes):
    return dict(
        id=key,
        title=key,
        kind="tasks",
        source="local",
        done=False,
        done_on=None,
        **changes,
    )


def event(title, stamp, **changes):
    return dict(
        title=title,
        date=stamp.date(),
        time=stamp.strftime("%H:%M"),
        start_dt=stamp,
        location="Example venue",
        **changes,
    )


class DailyAssistantTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.file = Path(self.folder.name) / "daily_lists.json"
        self.patch = patch.object(checklists, "FILE", self.file)
        self.patch.start()
        write_json(
            self.file,
            {"items": [task("First"), task("Second"), task("Third"), task("Fourth")]},
        )

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_focus_order_expiry_completion_skip_and_future_date(self):
        assistant.choose_focus(["Third", "First", "Second"], NOW.date())
        state = checklists.load()
        self.assertEqual(
            [row["id"] for row in assistant.briefing(state, now=NOW)["focus"]],
            ["Third", "First", "Second"],
        )
        self.assertEqual(
            assistant.briefing(state, now=NOW + timedelta(days=1))["focus"], []
        )
        state["items"][0]["done"] = True
        state["items"][1]["skipped_on"] = NOW.date().isoformat()
        self.assertEqual(
            [row["id"] for row in assistant.briefing(state, now=NOW)["focus"]],
            ["Third"],
        )
        state["items"][2]["due"] = "2026-10-14"
        self.assertEqual(assistant.briefing(state, now=NOW)["focus"], [])

    def test_tomorrow_plan_keeps_today_and_is_used_by_morning_print(self):
        assistant.choose_focus(["First"], NOW.date())
        assistant.choose_focus(["Second"], NOW.date() + timedelta(days=1))
        state = checklists.load()
        self.assertEqual(
            [row["id"] for row in assistant.briefing(state, now=NOW)["focus"]],
            ["First"],
        )
        morning = (NOW + timedelta(days=1)).replace(hour=3)
        self.assertEqual(
            [row["id"] for row in assistant.briefing(state, now=morning)["focus"]],
            ["Second"],
        )
        self.assertEqual(
            assistant.briefing(state, now=NOW + timedelta(days=2))["focus"], []
        )

    def test_invalid_focus_does_not_overwrite(self):
        for ids in (["First"] * 2, ["First", "Second", "Third", "Fourth"], ["missing"]):
            with self.assertRaises(ValueError):
                assistant.choose_focus(ids, NOW.date())
        self.assertNotIn("assistant", checklists.load())

    def test_next_appointment_skips_past_all_day_and_tomorrow(self):
        events = [
            event("Past", NOW - timedelta(hours=1)),
            dict(title="All day", date=NOW.date(), time="ALL DAY", all_day=True),
            event("Next", NOW + timedelta(hours=1)),
            event("Later", NOW + timedelta(hours=2)),
            event("Tomorrow", NOW + timedelta(days=1)),
        ]
        brief = assistant.briefing(checklists.load(), events, now=NOW)
        self.assertEqual(brief["appointment"]["index"], 2)
        self.assertIn("10:00 Next", brief["appointment"]["lines"])
        self.assertFalse(
            any("Leave by" in line for line in brief["appointment"]["lines"])
        )
        self.assertIsNone(
            assistant.briefing(checklists.load(), events, now=NOW.replace(hour=23))[
                "appointment"
            ]
        )

    def test_exact_title_preparation_and_explicit_travel_only(self):
        assistant.save_preparation("Next", 30, ["Pack ID"], ["Charge phone"])
        events = [event("NEXT", NOW + timedelta(hours=1))]
        lines = assistant.briefing(checklists.load(), events, now=NOW)["appointment"][
            "lines"
        ]
        self.assertIn("Leave by: Tue 13 Oct 09:30 BST", lines)
        self.assertIn("[ ] Pack ID", lines)
        events[0]["title"] = "Next interview"
        lines = assistant.briefing(checklists.load(), events, now=NOW)["appointment"][
            "lines"
        ]
        self.assertFalse(any("Leave by" in line for line in lines))
        assistant.save_preparation("Next", 15, ["Bring ticket"])
        self.assertEqual(checklists.load()["assistant"]["bedtime"], ["Charge phone"])
        self.assertEqual(len(checklists.load()["assistant"]["appointments"]), 1)
        assistant.save_preparation(remove="NEXT")
        self.assertEqual(checklists.load()["assistant"]["appointments"], [])

    def test_dst_travel_uses_elapsed_minutes_and_flags_passed_leave_time(self):
        assistant.save_preparation("Next", 60)
        stamp = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
        events = [event("Next", stamp)]
        now = datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)
        lines = assistant.briefing(checklists.load(), events, now=now)["appointment"][
            "lines"
        ]
        self.assertIn("Leave by: Sun 25 Oct 01:30 BST", lines)
        self.assertIn("Planned leave time has passed.", lines)

    def test_bedtime_early_appointments_and_deduplicated_preparation(self):
        assistant.save_preparation(
            "Early", None, ["Pack ID"], ["Pack ID", "Charge phone"]
        )
        tomorrow = NOW + timedelta(days=1)
        events = [
            event("Early", tomorrow.replace(hour=8)),
            event("Afternoon", tomorrow.replace(hour=12)),
        ]
        lines = assistant.briefing(checklists.load(), events, now=NOW)["bedtime"]
        self.assertIn("Tomorrow 08:00: Early", lines)
        self.assertNotIn("Tomorrow 12:00: Afternoon", lines)
        self.assertEqual(lines.count("[ ] Pack ID"), 1)

    def test_private_validation_and_no_write_on_bad_preparation(self):
        for minutes in (0, 241, True):
            with self.assertRaises(ValueError):
                assistant.save_preparation("Next", minutes)
        with self.assertRaises(ValueError):
            assistant.save_preparation("Next", prep=["one"] * 6)
        with self.assertRaises(ValueError):
            assistant.save_preparation("", prep=["Pack ID"])
        self.assertNotIn("assistant", checklists.load())
        # Backup validation uses the checklist validator, including assistant fields.
        from web_control.private_backup import _validate_file

        state = checklists.load()
        _validate_file("daily_lists.json", state)
        state["assistant"] = {"appointments": [{"title": "Next", "travel_minutes": -1}]}
        with self.assertRaises(ValueError):
            _validate_file("daily_lists.json", state)

    def test_legacy_saved_calendar_times_and_malformed_rows(self):
        events = [None, {"title": "Next", "date": "2026-10-13", "time": "10:00-11:00"}]
        self.assertEqual(
            assistant.briefing(checklists.load(), events, now=NOW)["appointment"][
                "index"
            ],
            1,
        )
        self.assertIsNone(
            assistant.briefing(checklists.load(), {"bad": "data"}, now=NOW)[
                "appointment"
            ]
        )

    def test_web_focus_day_guard_and_preparation_draft(self):
        from flask import Flask
        from web_control.task_tools import register

        app = Flask(__name__)
        app.secret_key = "test-only"
        register(app, lambda view: view)
        with (
            app.test_client() as client,
            patch.object(checklists, "today", return_value="2026-10-13"),
        ):
            self.assertEqual(
                client.post(
                    "/tasks/focus",
                    data={"focus_day": "2026-10-12", "focus_task": "First"},
                ).status_code,
                302,
            )
            self.assertNotIn("assistant", checklists.load())
            client.post(
                "/tasks/focus", data={"focus_day": "2026-10-13", "focus_task": "First"}
            )
            self.assertEqual(checklists.load()["assistant"]["focus"]["ids"], ["First"])
            with patch(
                "web_control.task_tools.render_template", return_value="retained draft"
            ) as render:
                response = client.post(
                    "/tasks/preparation",
                    data={
                        "appointment_title": "Next",
                        "travel_minutes": "-1",
                        "prep": "Pack ID",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    render.call_args.kwargs["prep_draft"]["prep"], "Pack ID"
                )

    def test_actions_pipeline_no_duplicates_and_preserves_triggers(
        self, paid_therapy=False
    ):
        from receipt.location_settings import DEFAULT_LOCATION, validate_location
        from services import vehicle_records

        saved_vehicles = [
            vehicle_records.record(
                {"registration": "AB12CDE", "insurance_expiry": "2027-01-01"}
            ),
            vehicle_records.record(
                {"registration": "XY34XYZ", "breakdown_expiry": "2027-02-01"}
            ),
        ]

        source = ast.parse(Path("services/live_pipeline.py").read_text())
        function = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_live_pipeline"
        )
        settings = deepcopy(DEFAULT_SETTINGS)
        settings["features"] = {key: key == "calendar" for key in settings["features"]}
        printer = Mock()
        printer.profile.profile_data = {"media": {"width": {"pixels": 0}}}
        output = []
        events = [event("Next appointment", NOW + timedelta(hours=1))]
        if paid_therapy:
            with checklists.transaction() as state:
                state["items"][0]["title"] = "Pay for therapy"
        assistant.choose_focus(["First"], NOW.date())
        assistant.save_preparation(
            "Next appointment", 30, ["Bring ticket"], ["Charge phone"]
        )
        namespace = dict(
            os=os,
            datetime=datetime,
            ZoneInfo=ZoneInfo,
            traceback=traceback,
            load_receipt_settings=lambda: settings,
            DEFAULT_LOCATION=DEFAULT_LOCATION,
            validate_location=validate_location,
            clear_route_cache=lambda: None,
            Usb=lambda *args: printer,
            PRINTER_VENDOR_ID=1,
            PRINTER_PRODUCT_ID=2,
            setup_printer=lambda *args: None,
            one_shot_requested=lambda *args: False,
            feature_enabled=lambda value, key: value["features"].get(key, False),
            preview_progress=lambda *args: None,
            vehicles=[{"registration": "AB12 CDE"}],
            dvla_api_key="",
            print_vehicle_expiry_checks=Mock(),
            CALENDAR_ICAL_URL="",
            GOOGLE_DOC_1_URL="",
            get_calendar_events=lambda *args, **kwargs: events,
            get_google_doc_text=lambda *args: "",
            therapy_payment_due=lambda *args: paid_therapy,
            therapy_paid_recently=lambda *args: paid_therapy,
            print_calendar=lambda p, rows: output.extend(row["title"] for row in rows),
            print_google_doc=lambda p, text, *args, **kwargs: output.extend(
                text.splitlines()
            ),
            print_line=lambda *args: None,
            left=lambda p, value: output.append(value),
            print_wrapped=lambda p, value, **kwargs: output.extend(
                textwrap.wrap(value, 40)
            ),
            printer_safe_text=printer_safe_text,
            finance_requested=Mock(return_value=False),
            food_shop_requested=lambda *args: False,
            shopping_list_requested=lambda *args: False,
            should_print_subscriptions=lambda: False,
            print_random_document_lines=lambda *args: output.append("WORKOUT"),
            cut_receipt_section=lambda *args: None,
        )
        exec(
            compile(
                ast.Module(body=[function], type_ignores=[]), "live_pipeline.py", "exec"
            ),
            namespace,
        )
        real_briefing = assistant.briefing
        with (
            patch.object(checklists, "today", return_value="2026-10-13"),
            patch.object(
                assistant,
                "briefing",
                side_effect=lambda state, events: real_briefing(state, events, now=NOW),
            ),
            patch(
                "services.bin_collections.reminder_lines",
                return_value=["[ ] Put out General today", "Collection: Wed 14 Oct"],
            ),
            patch("web_control.today_summary.save_calendar"),
            patch.object(
                vehicle_records,
                "load",
                return_value={"version": 1, "vehicles": saved_vehicles},
            ),
            patch(
                "actions.birthdays.receipt_lines",
                return_value=["Today: Example birthday (36)"],
            ),
            patch("builtins.print"),
        ):
            namespace["run_live_pipeline"](only_page="actions")
        printed = "\n".join(output)
        self.assertEqual(printed.count("First"), 0 if paid_therapy else 1)
        if paid_therapy:
            self.assertNotIn("Pay for therapy", printed)
        self.assertEqual(printed.count("Next appointment"), 1)
        self.assertEqual(printed.count("Put out General"), 1)
        self.assertEqual(printed.count("BIRTHDAYS"), 1)
        self.assertEqual(printed.count("Today: Example birthday (36)"), 1)
        self.assertEqual(printed.count("VEHICLES - SAVED DATES"), 1)
        self.assertEqual(printed.count("AB12CDE"), 1)
        self.assertEqual(printed.count("XY34XYZ"), 1)
        namespace["print_vehicle_expiry_checks"].assert_called_once_with(
            printer, [], ""
        )
        self.assertIn("BEFORE BED", printed)
        self.assertLess(printed.index("WORKOUT"), printed.index("BEFORE BED"))
        namespace["finance_requested"].assert_called_once_with(
            ("Pay for therapy" if paid_therapy else "First")
            + ".\nSecond.\nThird.\nFourth."
        )
        self.assertTrue(all(len(line) <= 40 for line in output))

    def test_paid_therapy_task_is_not_reintroduced_as_priority(self):
        self.test_actions_pipeline_no_duplicates_and_preserves_triggers(
            paid_therapy=True
        )
