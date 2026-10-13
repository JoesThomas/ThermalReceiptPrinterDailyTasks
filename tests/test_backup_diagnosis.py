import errno
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from web_control import maintenance, private_backup as backup

NOW = datetime(2026, 10, 13, 21, 40, tzinfo=timezone.utc)


class BackupDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "data").mkdir()
        self.file = self.root / "data" / "to_buy.json"

    def tearDown(self):
        self.folder.cleanup()

    def test_bad_json_names_only_supported_file_and_does_not_change_it(self):
        self.file.write_text("PRIVATE VALUE invalid JSON")
        with self.assertRaises(backup.BackupExportError) as result:
            backup.export(self.root)
        self.assertEqual(result.exception.filename, "to_buy.json")
        self.assertEqual(result.exception.kind, "invalid_json")
        self.assertNotIn("PRIVATE VALUE", str(result.exception))
        self.assertEqual(self.file.read_text(), "PRIVATE VALUE invalid JSON")

    def test_wrong_shape_and_current_assistant_data(self):
        self.file.write_text('{"items":"PRIVATE VALUE"}')
        with self.assertRaises(backup.BackupExportError) as result:
            backup.export(self.root)
        self.assertEqual(result.exception.kind, "invalid_data")
        self.assertNotIn("PRIVATE VALUE", str(result.exception))
        self.file.write_text('{"items":[]}')
        assistant = {
            "items": [],
            "assistant": {
                "focus": {"day": "2026-10-13", "ids": []},
                "other_focus": {"day": "2026-10-14", "ids": []},
                "appointments": [
                    {"title": "Appointment", "travel_minutes": 15, "prep": ["Pack ID"]}
                ],
                "bedtime": ["Charge phone"],
            },
        }
        (self.root / "data" / "daily_lists.json").write_text(json.dumps(assistant))
        self.assertEqual(
            backup.validate(backup.export(self.root))["files"]["daily_lists.json"],
            assistant,
        )

    def test_bounded_reads_and_no_linked_sources(self):
        self.file.write_bytes(b"x" * (backup.MAX_BYTES + 1))
        with self.assertRaises(backup.BackupExportError) as result:
            backup.export(self.root)
        self.assertEqual(result.exception.kind, "too_large")
        self.file.unlink()
        secret = self.root / "passwords.json"
        secret.write_text('{"items":["PRIVATE VALUE"]}')
        self.file.symlink_to(secret)
        with self.assertRaises(backup.BackupExportError) as result:
            backup.export(self.root)
        self.assertEqual(result.exception.kind, "linked_file")
        self.assertNotIn("passwords", str(result.exception))

    def test_backoff_manual_retry_and_recovery(self):
        self.file.write_text("invalid")
        with self.assertRaises(ValueError):
            maintenance.create(self.root, now=NOW)
        state = maintenance.attempt_state(self.root)
        self.assertEqual(state["state"], "failed")
        self.assertEqual(
            datetime.fromisoformat(state["next_retry"]), NOW + timedelta(minutes=15)
        )
        self.file.write_text('{"items":[]}')
        self.assertFalse(maintenance.create(self.root, now=NOW + timedelta(minutes=1)))
        self.assertTrue(
            maintenance.create(self.root, force=True, now=NOW + timedelta(minutes=2))
        )
        self.assertEqual(maintenance.attempt_state(self.root)["state"], "saved")
        self.assertEqual(len(maintenance.saved(self.root)), 1)

    def test_empty_install_is_idle_without_failed_warning(self):
        self.assertFalse(maintenance.create(self.root, now=NOW))
        self.assertEqual(maintenance.attempt_state(self.root)["state"], "idle")

    def test_loop_deduplicates_warnings_and_runs_independent_jobs(self):
        self.file.write_text("invalid PRIVATE VALUE")
        warnings = {}
        with (
            patch("web_control.backup_health.check") as recovery,
            patch("receipt.lifestyle.prune") as lifestyle,
            patch("receipt.lifestyle.prune_explanations") as explanations,
            patch("receipt.archive_policy.prune") as archives,
            patch.object(
                maintenance.backup, "export", wraps=backup.export
            ) as exporting,
            patch.object(maintenance.logging, "getLogger") as logger,
        ):
            for minutes in (0, 1, 2, 15, 30):
                maintenance.run_once(
                    self.root, warnings=warnings, now=NOW + timedelta(minutes=minutes)
                )
            self.assertEqual(exporting.call_count, 3)
            self.assertEqual(logger.return_value.warning.call_count, 1)
            self.assertEqual(lifestyle.call_count, 5)
            self.assertEqual(recovery.call_count, 5)
            self.assertEqual(explanations.call_count, 5)
            self.assertEqual(archives.call_count, 5)
            warning = logger.return_value.warning.call_args.args
            self.assertIn("to_buy.json", warning[-1])
            self.assertNotIn("PRIVATE VALUE", str(warning))
            self.file.write_text('{"items":[]}')
            maintenance.run_once(
                self.root, warnings=warnings, now=NOW + timedelta(minutes=45)
            )
            logger.return_value.info.assert_called_once_with(
                "%s available again.", "Private backup"
            )

    def test_other_maintenance_failure_is_not_called_backup_failure(self):
        self.file.write_text('{"items":[]}')
        with (
            patch("web_control.backup_health.check"),
            patch("receipt.lifestyle.prune"),
            patch("receipt.lifestyle.prune_explanations"),
            patch(
                "receipt.archive_policy.prune", side_effect=ValueError("PRIVATE VALUE")
            ),
            patch.object(maintenance.logging, "getLogger") as logger,
        ):
            maintenance.run_once(self.root, now=NOW)
            self.assertEqual(maintenance.attempt_state(self.root)["state"], "saved")
            self.assertEqual(
                logger.return_value.warning.call_args.args[1], "Receipt archive cleanup"
            )
            self.assertNotIn(
                "PRIVATE VALUE", str(logger.return_value.warning.call_args)
            )

    def test_io_failures_are_actionable_without_exception_values(self):
        error = OSError(errno.ENOSPC, "PRIVATE VALUE", "/private/user/data/to_buy.json")
        self.assertIn("disk space", backup.failure_message(error))
        self.assertIn("to_buy.json", backup.failure_message(error))
        self.assertNotIn("PRIVATE VALUE", backup.failure_message(error))
        self.assertNotIn("/private/user", backup.failure_message(error))
        self.assertIn(
            "Permission denied",
            backup.failure_message(PermissionError(errno.EACCES, "SECRET")),
        )

    def test_disk_full_still_warns_once_when_status_cannot_be_written(self):
        warnings = {}
        with (
            patch.object(
                maintenance,
                "_create",
                side_effect=OSError(errno.ENOSPC, "PRIVATE VALUE"),
            ),
            patch(
                "storage.write_json", side_effect=OSError(errno.ENOSPC, "PRIVATE VALUE")
            ),
            patch("web_control.backup_health.check"),
            patch("receipt.lifestyle.prune"),
            patch("receipt.lifestyle.prune_explanations"),
            patch("receipt.archive_policy.prune"),
            patch.object(maintenance.logging, "getLogger") as logger,
        ):
            maintenance.run_once(self.root, warnings=warnings, now=NOW)
            maintenance.run_once(
                self.root, warnings=warnings, now=NOW + timedelta(minutes=1)
            )
            logger.return_value.warning.assert_called_once()
            self.assertNotIn(
                "PRIVATE VALUE", str(logger.return_value.warning.call_args)
            )
