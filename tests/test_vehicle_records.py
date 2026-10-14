import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from services import vehicle_records as records
from web_control import private_backup


class VehicleRecordsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.file = self.root / "data" / "vehicles.json"
        self.patch = patch.object(records, "FILE", self.file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_multiple_vehicles_edit_remove_and_private_permissions(self):
        records.update(
            {"registration": "ab12 cde", "name": "Car", "mot_expiry": "2027-01-01"}
        )
        records.update(
            {
                "registration": "XY34XYZ",
                "insurance_expiry": "2026-12-01",
                "breakdown_provider": "Example cover",
            }
        )
        rows = records.load()["vehicles"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["registration"], "AB12CDE")
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        records.update(dict(rows[0], tax_due="2027-02-01"), rows[0]["id"])
        self.assertEqual(records.load()["vehicles"][-1]["tax_due"], "2027-02-01")
        records.update({}, rows[1]["id"], True)
        self.assertEqual(len(records.load()["vehicles"]), 1)

    def test_invalid_dates_duplicates_and_unknown_ids_do_not_replace_data(self):
        records.update({"registration": "AB12CDE"})
        before = self.file.read_bytes()
        for values, key in [
            ({"registration": "AB12 CDE"}, ""),
            ({"registration": "XY34XYZ", "mot_expiry": "2027-02-29"}, ""),
            ({"registration": "XY34XYZ", "tax_due": "20270101"}, ""),
            ({"registration": "<script>"}, ""),
            ({"registration": "XY34XYZ"}, "a" * 32),
        ]:
            with self.assertRaises(ValueError):
                records.update(values, key)
            self.assertEqual(self.file.read_bytes(), before)

    def test_corrupt_file_is_preserved_and_not_reset(self):
        self.file.parent.mkdir()
        self.file.write_text("invalid private data")
        with self.assertRaises(ValueError):
            records.update({"registration": "AB12CDE"})
        self.assertEqual(self.file.read_text(), "invalid private data")

    def test_expiry_labels_past_today_soon_future_and_unknown(self):
        today = date(2026, 10, 14)
        self.assertIn(
            "1 day past recorded date", records.expiry_label("2026-10-13", today)
        )
        self.assertIn("due today", records.expiry_label("2026-10-14", today))
        self.assertIn("in 31 days", records.expiry_label("2026-11-14", today))
        self.assertEqual(records.expiry_label("2027-01-01", today), "01 Jan 2027")
        self.assertEqual(records.expiry_label("", today), "Not recorded")

    def test_receipt_all_four_dates_and_cover_details_without_network(self):
        row = records.record(
            {
                "registration": "AB12CDE",
                "name": "Car",
                "mot_expiry": "2026-10-14",
                "tax_due": "2026-10-21",
                "insurance_expiry": "2027-02-01",
                "breakdown_expiry": "2027-03-01",
                "insurance_provider": "Example insurer",
                "insurance_reference": "REF123",
                "breakdown_provider": "Example breakdown",
                "breakdown_reference": "MEMBER123",
            }
        )
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("remote lookup"),
        ):
            lines = records.receipt_lines([row], date(2026, 10, 14))
        for label in (
            "MOT:",
            "Tax:",
            "Insurance:",
            "Breakdown:",
            "REF123",
            "MEMBER123",
        ):
            self.assertIn(label, "\n".join(lines))
        self.assertEqual(records.receipt_lines([]), [])

    def test_backups_restore_all_vehicles_and_reject_bad_dates(self):
        records.update({"registration": "AB12CDE", "insurance_expiry": "2027-01-01"})
        saved = records.load()
        value = private_backup.validate(private_backup.export(self.root))
        records.update({}, saved["vehicles"][0]["id"], True)
        private_backup.restore(self.root, value)
        self.assertEqual(records.load(), saved)
        value["files"]["vehicles.json"]["vehicles"][0]["mot_expiry"] = "2027-02-29"
        with self.assertRaises(ValueError):
            private_backup.validate(json.dumps(value).encode())

    def test_web_save_invalid_draft_and_remove(self):
        from flask import Flask
        from web_control.vehicle_tools import register

        app = Flask(__name__)
        app.secret_key = "test-only"
        register(app, lambda view: view)
        with app.test_client() as client:
            self.assertEqual(
                client.post(
                    "/vehicles/save", data={"registration": "AB12CDE"}
                ).status_code,
                302,
            )
            row = records.load()["vehicles"][0]
            with patch(
                "web_control.vehicle_tools.render_template", return_value="draft"
            ) as render:
                response = client.post(
                    "/vehicles/save",
                    data={
                        "id": row["id"],
                        "registration": "AB12CDE",
                        "mot_expiry": "invalid",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    render.call_args.kwargs["draft"]["mot_expiry"], "invalid"
                )
            self.assertEqual(
                client.post(
                    "/vehicles/save", data={"id": row["id"], "action": "remove"}
                ).status_code,
                302,
            )
            self.assertEqual(records.load()["vehicles"], [])

    def test_sunday_prints_all_vehicles_even_without_dates(self):
        rows = [
            records.record({"registration": "AB12CDE"}),
            records.record({"registration": "XY34XYZ", "mot_expiry": "2027-01-01"}),
        ]
        lines = "\n".join(records.receipt_lines(rows, date(2026, 10, 18)))
        self.assertIn("AB12CDE", lines)
        self.assertIn("XY34XYZ", lines)

    def test_weekday_exact_milestones_for_every_date_field(self):
        from datetime import timedelta

        today = date(2026, 10, 14)
        for field in records.DATES:
            for days in (30, 14, 7, 31, 29, 15, 13, 8, 6, 0, -1):
                with self.subTest(field=field, days=days):
                    row = records.record(
                        {
                            "registration": "AB12CDE",
                            field: (today + timedelta(days=days)).isoformat(),
                        }
                    )
                    self.assertEqual(
                        bool(records.receipt_lines([row], today)), days in {30, 14, 7}
                    )

    def test_weekday_prints_only_qualifying_vehicle_and_only_once(self):
        rows = [
            records.record(
                {
                    "registration": "AB12CDE",
                    "mot_expiry": "2026-10-21",
                    "tax_due": "2026-10-28",
                }
            ),
            records.record({"registration": "XY34XYZ", "mot_expiry": "2026-10-22"}),
        ]
        lines = "\n".join(records.receipt_lines(rows, date(2026, 10, 14)))
        self.assertEqual(lines.count("AB12CDE"), 1)
        self.assertNotIn("XY34XYZ", lines)
        with patch.object(records, "uk_today", return_value=date(2026, 10, 14)):
            self.assertEqual(
                records.receipt_lines(rows),
                records.receipt_lines(rows, date(2026, 10, 14)),
            )
