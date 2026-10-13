import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from receipt_settings import settings_diagnosis
from web_control import private_backup as backup


class SettingsBackupDiagnosisTests(unittest.TestCase):
    def test_field_and_value_reasons_without_private_values(self):
        cases = [
            (
                {"display": {"weather_detail": "PRIVATE VALUE"}},
                "Invalid weather detail.",
            ),
            ({"features": {"calendar": "PRIVATE VALUE"}}, "Invalid features calendar."),
            (
                {"print_schedule": {"time": "PRIVATE VALUE"}},
                "Invalid daily print time.",
            ),
            ({"layout": {"order": ["actions"] * 4}}, "Choose each receipt page once."),
            ({"location": {"latitude": "PRIVATE VALUE"}}, "Enter a valid latitude."),
            ({"schema_version": 2}, "Unsupported private schema version"),
        ]
        for raw, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(settings_diagnosis(raw), reason)
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "data").mkdir()
                    source = root / "data" / "receipt_settings.json"
                    original = json.dumps(raw)
                    source.write_text(original)
                    with self.assertRaises(backup.BackupExportError) as result:
                        backup.export(root)
                    self.assertIn(reason, str(result.exception))
                    self.assertNotIn("PRIVATE VALUE", str(result.exception))
                    self.assertEqual(source.read_text(), original)

    def test_legacy_partial_and_current_valid_settings_need_no_repair(self):
        for raw in (
            {},
            {"features": {"calendar": False}},
            {"schema_version": 1, "print_schedule": {"time": "03:00"}},
        ):
            self.assertIsNone(settings_diagnosis(raw))

    def test_unrecognised_exception_message_is_not_exposed(self):
        with patch(
            "receipt_settings.validate_settings",
            side_effect=ValueError("PRIVATE VALUE"),
        ):
            self.assertEqual(
                settings_diagnosis({}), "Receipt settings failed validation."
            )

    def test_last_good_file_also_gets_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "receipt_settings.last-good.json").write_text(
                '{"private_backup":{"keep":99}}'
            )
            with self.assertRaises(backup.BackupExportError) as result:
                backup.export(root)
            self.assertIn("receipt_settings.last-good.json", str(result.exception))
            self.assertIn("Invalid backup retention.", str(result.exception))

    def test_targeted_weather_repair_preserves_other_keys_and_exact_original(self):
        import receipt_settings as settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt_settings.json"
            original = b'{"display":{"weather_detail":"legacy","news_count":5},"features":{"calendar":false},"extra":{"owner_note":"PRIVATE VALUE"}}'
            path.write_bytes(original)
            last_good = Path(directory) / "receipt_settings.last-good.json"
            last_good.write_text('{"display":{"weather_detail":"brief"}}')
            with patch.object(settings, "SETTINGS_FILE", path):
                preserved = settings.repair_weather_detail()
                repaired = json.loads(path.read_text())
                expected = json.loads(original)
                expected["display"]["weather_detail"] = "full"
                self.assertEqual(repaired, expected)
                self.assertEqual(preserved.read_bytes(), original)
                self.assertEqual(
                    last_good.read_text(), '{"display":{"weather_detail":"brief"}}'
                )
                self.assertIsNone(settings.repair_weather_detail())

    def test_weather_repair_does_not_reset_other_invalid_or_newer_settings(self):
        import receipt_settings as settings

        for raw in (
            {
                "display": {"weather_detail": "legacy"},
                "print_schedule": {"time": "bad"},
            },
            {"display": {"weather_detail": "legacy"}, "schema_version": 2},
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipt_settings.json"
                original = json.dumps(raw).encode()
                path.write_bytes(original)
                with (
                    patch.object(settings, "SETTINGS_FILE", path),
                    self.assertRaises(ValueError),
                ):
                    settings.repair_weather_detail()
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(Path(directory).glob("*.invalid-*.json")), [])
