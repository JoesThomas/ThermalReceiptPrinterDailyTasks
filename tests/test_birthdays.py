import base64
import json
import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from actions import birthdays
from web_control import private_backup as backup
from deployment.update_helper import config_payload

HEADER = b"Name,Year,Month,Day,Link to Profile\n"
DATA = (
    HEADER
    + b"Example Person,1990,10,13,https://facebook.com/123\nOther Person,,10,14,\n,,,,\n"
)


class BirthdayTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.file = self.root / "data" / "birthdays.csv"
        self.patches = [
            patch.object(birthdays, "FILE", self.file),
            patch.object(birthdays, "today", return_value=date(2026, 10, 13)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def test_import_removes_blanks_preserves_unknown_year_and_is_idempotent(self):
        result = birthdays.import_csv(DATA)
        self.assertEqual(result, {"blank": 1, "duplicates": 0, "added": 2, "total": 2})
        rows = birthdays.load()
        self.assertIsNone(rows[1]["year"])
        self.assertEqual(birthdays.import_csv(DATA)["added"], 0)
        self.assertEqual(len(birthdays.load()), 2)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_exact_duplicate_removed_conflicting_duplicate_rejects_whole_import(self):
        identical = HEADER + b"Example Person,1990,10,13,https://facebook.com/123\n" * 2
        self.assertEqual(birthdays.import_csv(identical)["duplicates"], 1)
        before = self.file.read_bytes()
        conflicting = HEADER + b"Example Person,1990,10,14,https://facebook.com/123\n"
        with self.assertRaises(ValueError):
            birthdays.import_csv(conflicting)
        self.assertEqual(self.file.read_bytes(), before)
        with self.assertRaises(ValueError):
            birthdays.import_csv(HEADER + b"Valid Person,,1,1,\nBad Person,,2,30,\n")
        self.assertEqual(self.file.read_bytes(), before)

    def test_old_profile_columns_are_discarded_and_conflicting_names_rejected(self):
        raw = (
            HEADER
            + b"Example Person,1990,10,13,https://facebook.com/123\nExample Person,1980,11,13,https://facebook.com/456\n"
        )
        with self.assertRaises(ValueError):
            birthdays.import_csv(raw)
        birthdays.import_csv(DATA)
        self.assertNotIn("profile", birthdays.load()[0])
        self.assertNotIn(b"Link to Profile", self.file.read_bytes())

    def test_edit_and_remove_keep_identity_and_reimport_does_not_undo_edits(self):
        birthdays.import_csv(DATA)
        first = birthdays.load()[0]
        birthdays.update("Renamed Person", 1989, 10, 13, first["id"])
        self.assertEqual(birthdays.load()[0]["id"], first["id"])
        before = self.file.read_bytes()
        with self.assertRaises(ValueError):
            birthdays.import_csv(DATA)
        self.assertEqual(self.file.read_bytes(), before)
        birthdays.update(key=first["id"], remove=True)
        self.assertEqual(len(birthdays.load()), 1)
        with self.assertRaises(ValueError):
            birthdays.update(key=first["id"], remove=True)

    def test_valid_dates_and_leap_days_without_inventing_a_year(self):
        for year, month, day in (
            ("", 2, 30),
            (2025, 2, 29),
            (2027, 1, 1),
            (2026, 12, 1),
        ):
            with self.assertRaises(ValueError):
                birthdays.record("Example", year, month, day)
        row = birthdays.record("Leap birthday", "", 2, 29)
        self.assertEqual(birthdays.upcoming([row], date(2027, 2, 28), 1), [])
        self.assertEqual(
            birthdays.upcoming([row], date(2028, 2, 28), 1)[0]["when"], "Tomorrow"
        )
        self.assertIsNone(birthdays.upcoming([row], date(2028, 2, 28), 1)[0]["age"])

    def test_receipt_today_upcoming_age_and_year_boundary(self):
        birthdays.import_csv(DATA)
        self.assertEqual(
            birthdays.receipt_lines(date(2026, 10, 13)),
            ["Today: Example Person (36)"],
        )
        row = birthdays.record("New Year", 2000, 1, 1)
        result = birthdays.upcoming([row], date(2026, 12, 31), 1)[0]
        self.assertEqual(result["age"], 27)
        self.assertEqual(result["when"], "Tomorrow")

    def test_csv_limits_bad_columns_and_formula_names(self):
        for data in (
            b"Bad,Columns\nfoo,bar\n",
            DATA + b"Broken,,1,1,,EXTRA\n",
            b"x" * (birthdays.MAX_BYTES + 1),
            HEADER + b"=BAD,,1,1,\n",
        ):
            with self.assertRaises(ValueError):
                birthdays.parse_csv(data)

    def test_backup_restore_and_update_checkpoint_preserve_csv_records(self):
        birthdays.import_csv(DATA)
        rows = birthdays.load()
        exported = backup.export(self.root)
        value = backup.validate(exported)
        self.assertEqual(value["files"]["birthdays.csv"]["rows"], rows)
        checkpoint = {
            "files": {
                "birthdays.csv": base64.b64encode(self.file.read_bytes()).decode()
            }
        }
        self.assertEqual(
            backup.validate(config_payload(checkpoint))["files"]["birthdays.csv"][
                "rows"
            ],
            rows,
        )
        birthdays.update(key=rows[0]["id"], remove=True)
        backup.restore(self.root, value)
        self.assertEqual(birthdays.load(), rows)
        self.assertNotIn("PRIVATE TOKEN", exported.decode())

    def test_web_import_edit_export_and_invalid_draft(self):
        from flask import Flask
        from web_control.birthday_tools import register

        app = Flask(__name__)
        app.secret_key = "test-only"
        register(app, lambda view: view)
        with app.test_client() as client:
            response = client.post(
                "/birthdays/import", data={"file": (BytesIO(DATA), "source.csv")}
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(len(birthdays.load()), 2)
            first = birthdays.load()[0]
            response = client.post(
                "/birthdays/save",
                data={
                    "id": first["id"],
                    "name": "Updated",
                    "year": "1991",
                    "month": "10",
                    "day": "13",
                },
            )
            self.assertEqual(response.status_code, 302)
            with patch(
                "web_control.birthday_tools.render_template", return_value="draft"
            ) as rendering:
                response = client.post(
                    "/birthdays/save", data={"name": "Draft", "month": "2", "day": "30"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(rendering.call_args.kwargs["draft"]["name"], "Draft")
            exported = client.get("/birthdays/export")
            self.assertEqual(exported.status_code, 200)
            self.assertIn("birthdays.csv", exported.headers["Content-Disposition"])
            rows, _ = birthdays.parse_csv(exported.data)
            self.assertEqual(rows, birthdays.load())

    def test_four_column_import_keeps_legacy_ids_and_backup_restore_drops_links(self):
        old_id = "a" * 32
        legacy = (
            b"Name,Year,Month,Day,Link to Profile,ID\nExample Person,1990,10,13,https://facebook.com/123,"
            + old_id.encode()
            + b"\n"
        )
        birthdays.import_csv(legacy)
        birthdays.import_csv(b"Name,Year,Month,Day\nExample Person,1990,10,13\n")
        self.assertEqual(len(birthdays.load()), 1)
        self.assertEqual(birthdays.load()[0]["id"], old_id)
        old_row = dict(birthdays.load()[0], profile="https://facebook.com/123")
        value = backup.validate(
            json.dumps(
                {"version": 1, "files": {"birthdays.csv": {"rows": [old_row]}}}
            ).encode()
        )
        self.assertNotIn("profile", value["files"]["birthdays.csv"]["rows"][0])
        backup.restore(self.root, value)
        self.assertNotIn(b"facebook", self.file.read_bytes())

    def test_sunday_ten_day_receipt_and_weekday_birthday_only(self):
        birthdays.import_csv(
            b"Name,Year,Month,Day\nToday person,1990,10,18\nTen days,,10,28\nEleven days,,10,29\n"
        )
        lines = birthdays.receipt_lines(date(2026, 10, 18))
        self.assertIn("Today: Today person (36)", lines)
        self.assertTrue(any("Ten days" in line for line in lines))
        self.assertFalse(any("Eleven days" in line for line in lines))
        self.assertEqual(birthdays.receipt_lines(date(2026, 10, 19)), [])
        self.assertEqual(
            birthdays.receipt_lines(date(2026, 10, 28)), ["Today: Ten days"]
        )
