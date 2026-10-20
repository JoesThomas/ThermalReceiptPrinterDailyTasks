from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from receipt import archive, archive_policy
from receipt.profile import COLUMNS, PRINTABLE_PIXELS, printable_width
from receipt.weather_renderers import WeatherDependencies
from services.mail_source import (
    GmailConfig,
    collect,
    _extract_imap_message_body,
    _decode_email_header,
    _likely_delivery_email,
)
from storage import write_json
from tools.receipt_visual_fixture import weather_capture
import email


class WeatherAndProfileTests(TestCase):
    def test_compact_tables_and_unchanged_order(self):
        text, images = weather_capture()
        self.assertIn("Maximum Minimum Rain Sunrise Sunset", text)
        self.assertIn("14.1C   7.3C    0%   07:25   18:22", text)
        self.assertIn("Time  Temp  Humidity Wind    Weather", text)
        self.assertNotIn("marks the current", text)
        rows = [row.lstrip() for row in text.splitlines()
                if row.lstrip()[:5].replace(":", "").isdigit() and ":" in row.lstrip()[:5]]
        self.assertTrue(any(row.startswith("12:00 13.2C") for row in rows))
        self.assertEqual(len(rows), 24)
        self.assertLess(text.index("TODAY"), text.index("TEMPERATURE GRAPH"))
        self.assertLess(text.index("TEMPERATURE GRAPH"), text.index("HOURLY WEATHER"))
        self.assertEqual(len(images), 1)

    def test_profile_and_renderer_are_independent_of_live_configuration(self):
        self.assertEqual(COLUMNS, 46)
        self.assertEqual(PRINTABLE_PIXELS, 576)
        self.assertEqual(printable_width(object()), PRINTABLE_PIXELS)
        deps = WeatherDependencies()
        self.assertTrue(callable(deps.left))
        self.assertTrue(callable(deps.weather_description))
        with patch.dict("sys.modules", {"services.live_pipeline": None}):
            self.assertTrue(weather_capture()[0])


class ArchivePolicyTests(TestCase):
    def fixture(self, folder):
        directory = Path(folder) / "data" / "receipt_archive"
        directory.mkdir(parents=True)
        return directory

    def test_default_keeps_all_and_storage_counts_without_reading_contents(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(archive, "DIRECTORY", self.fixture(folder)),
        ):
            identifier = archive.save(
                {"information": "old receipt"},
                {},
                "2020-01-01T12:00:00+00:00",
                "preview",
                {},
            )
            self.assertEqual(archive_policy.prune(folder, force=True), 0)
            with patch.object(
                archive,
                "load",
                side_effect=AssertionError("Storage stats read receipt payload"),
            ):
                usage = archive_policy.usage(folder)
            self.assertEqual(usage["count"], 1)
            self.assertGreater(usage["bytes"], 0)
            self.assertTrue((archive.DIRECTORY / (identifier + ".json")).exists())

    def test_retention_preserves_pinned_recent_corrupt_and_symlink_receipts(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(archive, "DIRECTORY", self.fixture(folder)),
        ):
            now = datetime(2026, 10, 12, tzinfo=timezone.utc)
            old = "2026-01-01T12:00:00+00:00"
            first = archive.save({"information": "old"}, {}, old, "preview", {})
            pinned = archive.save({"information": "pinned"}, {}, old, "preview", {})
            recent = archive.save(
                {"information": "recent"}, {}, now.isoformat(), "preview", {}
            )
            corrupt = archive.DIRECTORY / "20200101T000000Z-abcdefabcdef.json"
            corrupt.write_text("bad")
            target = Path(folder) / "external.json"
            target.write_text("keep")
            link = archive.DIRECTORY / "20200101T000000Z-abcdabcdabcd.json"
            link.symlink_to(target)
            archive_policy.pin(pinned, True, folder)
            archive_policy.save(30, folder)
            self.assertEqual(archive_policy.prune(folder, now=now, force=True), 1)
            self.assertFalse((archive.DIRECTORY / (first + ".json")).exists())
            for identifier in (pinned, recent):
                self.assertTrue((archive.DIRECTORY / (identifier + ".json")).exists())
            self.assertTrue(corrupt.exists())
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), "keep")
            self.assertEqual(archive_policy.prune(folder, now=now), 0)
            archive_policy.pin(pinned, False, folder)
            self.assertEqual(archive_policy.prune(folder, now=now, force=True), 1)

    def test_invalid_policy_never_overwrites_saved_settings_and_backup_validates(self):
        with TemporaryDirectory() as folder:
            archive_policy.save(90, folder)
            path = archive_policy.store(folder).path
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                archive_policy.save(2, folder)
            self.assertEqual(path.read_bytes(), before)
            from web_control.private_backup import _validate_file

            _validate_file(
                "receipt_archive_settings.json", archive_policy.options(folder)
            )
            with self.assertRaises(ValueError):
                archive_policy.validate({"keep_days": 30, "pins": [["bad"]]})


class MailSourceTests(TestCase):
    def test_message_parsing_handles_headers_and_ignores_attachments(self):
        message = email.message_from_string(
            "Subject: =?utf-8?b?UGFyY2VsIGRpc3BhdGNoZWQ=?=\nContent-Type: text/plain; charset=utf-8\n\nYour parcel is on its way."
        )
        self.assertEqual(_decode_email_header(message["Subject"]), "Parcel dispatched")
        self.assertIn("on its way", _extract_imap_message_body(message))
        self.assertTrue(_likely_delivery_email("Parcel dispatched", "Your parcel"))
        message["Content-Disposition"] = "attachment"
        self.assertEqual(_extract_imap_message_body(message), "")

    def test_disabled_credentials_do_not_connect(self):
        with patch("services.mail_source.imaplib.IMAP4_SSL") as connect:
            self.assertEqual(collect(GmailConfig("", "")), ([], False))
        connect.assert_not_called()

    def test_timeout_returns_failure_and_always_closes_mailbox(self):
        mailbox = Mock()
        mailbox.login.side_effect = TimeoutError("private password")
        with patch("services.mail_source.imaplib.IMAP4_SSL", return_value=mailbox):
            records, failed = collect(
                GmailConfig("example.invalid", "private password")
            )
        self.assertEqual(records, [])
        self.assertTrue(failed)
        mailbox.logout.assert_called_once()
