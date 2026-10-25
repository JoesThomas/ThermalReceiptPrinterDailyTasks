from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import json
from flask import Flask
from finance import scenario_presets, savings_goals
from finance.scenario_plan import build
from finance.transfer_explanation import explain
from receipt import archive, build_info
from storage import PrivateStateError
import receipt_settings as settings

TODAY = date(2026, 10, 12)


def values(**changes):
    return dict(
        dict(
            salary="1000",
            start=str(TODAY),
            months="2",
            strategy="amex_first",
            save_all="on",
            invest_spare_cash="on",
        ),
        **changes,
    )


def base(balance="3549.94"):
    return {
        "valid": True,
        "cash": D(1200),
        "buffer": D(1000),
        "daily": D(10),
        "warnings": [],
        "amex": {"balance": D(balance), "scheduled": True},
        "events": [
            {"name": "Amex payment", "date": date(2026, 10, 25), "amount": D(50)}
        ],
    }


class SettingsRecoveryTests(TestCase):
    def test_recovery_preserves_damaged_file_and_last_good_values(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(
                settings, "SETTINGS_FILE", Path(folder) / "receipt_settings.json"
            ),
        ):
            value = settings.load_receipt_settings()
            value["features"]["weather"] = False
            settings.save_receipt_settings(value)
            self.assertEqual(
                json.loads(settings.SETTINGS_FILE.read_text())["schema_version"], 1
            )
            settings.SETTINGS_FILE.write_text("{broken")
            recovered, warning = settings.settings_state()
            self.assertFalse(recovered["features"]["weather"])
            self.assertFalse(recovered["print_schedule"]["enabled"])
            self.assertTrue(warning)
            self.assertEqual(settings.SETTINGS_FILE.read_text(), "{broken")
            settings.save_receipt_settings(recovered)
            self.assertIsNone(settings.settings_state()[1])
            self.assertEqual(len(list(Path(folder).glob("*.invalid-*.json"))), 1)
            self.assertEqual(
                next(Path(folder).glob("*.invalid-*.json")).read_text(), "{broken"
            )

    def test_wrong_types_and_values_are_not_silently_accepted(self):
        for raw in (
            {"features": {"weather": "false"}},
            {"features": []},
            {"display": {"news_count": True}},
            {"location": {"latitude": "nan"}},
            {"print_schedule": {"time": "25:00"}},
            {"schema_version": True},
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                settings.validate_settings(raw)

    def test_no_good_copy_warns_and_pauses_automatic_requests(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(
                settings, "SETTINGS_FILE", Path(folder) / "receipt_settings.json"
            ),
        ):
            settings.SETTINGS_FILE.write_text("[]")
            result, warning = settings.settings_state()
            self.assertIn("no working copy", warning)
            self.assertFalse(result["print_schedule"]["enabled"])
            self.assertFalse(any(result["one_shot"].values()))
            self.assertFalse(settings.last_good_file().exists())

    def test_legacy_partial_settings_migrate_only_on_save(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(
                settings, "SETTINGS_FILE", Path(folder) / "receipt_settings.json"
            ),
        ):
            original = '{"features":{"weather":false}}'
            settings.SETTINGS_FILE.write_text(original)
            loaded = settings.load_receipt_settings()
            self.assertFalse(loaded["features"]["weather"])
            self.assertEqual(settings.SETTINGS_FILE.read_text(), original)
            settings.save_receipt_settings(loaded)
            self.assertEqual(
                json.loads(settings.SETTINGS_FILE.read_text())["schema_version"], 1
            )

    def test_newer_settings_cannot_be_downgraded(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(
                settings, "SETTINGS_FILE", Path(folder) / "receipt_settings.json"
            ),
        ):
            original = '{"schema_version":2,"future":true}'
            settings.SETTINGS_FILE.write_text(original)
            with self.assertRaises(ValueError):
                settings.save_receipt_settings(deepcopy(settings.DEFAULT_SETTINGS))
            self.assertEqual(settings.SETTINGS_FILE.read_text(), original)


class ScenarioPresetTests(TestCase):
    def test_round_trip_excludes_credentials_and_preserves_unchecked_options(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(scenario_presets, "FILE", Path(folder) / "scenarios.json"),
        ):
            identifier = scenario_presets.save(
                "Amex first", values(csrf_token="secret", unrelated="ignored"), TODAY
            )
            row = scenario_presets.load(identifier)
            self.assertNotIn("csrf_token", row["values"])
            self.assertNotIn("unrelated", row["values"])
            self.assertEqual(row["values"]["equal_savings"], "")
            same = scenario_presets.save("Amex FIRST", values(salary="1500"), TODAY)
            self.assertEqual(same, identifier)
            self.assertEqual(len(scenario_presets.listing()), 1)
            self.assertEqual(
                scenario_presets.load(identifier)["values"]["salary"], "1500"
            )
            self.assertEqual(scenario_presets.FILE.stat().st_mode & 0o777, 0o600)
            scenario_presets.delete(identifier)
            self.assertEqual(scenario_presets.listing(), [])

    def test_old_scenario_remains_loadable_but_needs_date_review(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(scenario_presets, "FILE", Path(folder) / "scenarios.json"),
        ):
            identifier = scenario_presets.save("Saved plan", values(), TODAY)
            row = scenario_presets.load(identifier)
            with self.assertRaises(ValueError):
                scenario_presets.validate_inputs(row["values"], date(2026, 11, 1))
            self.assertEqual(scenario_presets.load(identifier), row)

    def test_invalid_input_does_not_create_or_replace_state(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(scenario_presets, "FILE", Path(folder) / "scenarios.json"),
        ):
            identifier = scenario_presets.save("Plan", values(), TODAY)
            original = scenario_presets.FILE.read_bytes()
            for name, data in (
                ("", values()),
                ("Plan", values(opening_cash="-1")),
                ("Plan", values(salary="bad")),
            ):
                with self.assertRaises(ValueError):
                    scenario_presets.save(name, data, TODAY)
                self.assertEqual(scenario_presets.FILE.read_bytes(), original)
            state = json.loads(original)
            state["schema_version"] = 2
            scenario_presets.FILE.write_text(json.dumps(state))
            with self.assertRaises(PrivateStateError):
                scenario_presets.delete(identifier)

    def test_load_route_fills_form_without_bank_lookup_or_old_receipt(self):
        from web_control.test_finance_tools import register

        app = Flask(__name__)
        app.secret_key = "tests"
        start_print = Mock()
        register(app, lambda function: function, start_print)
        with (
            TemporaryDirectory() as folder,
            patch.object(scenario_presets, "FILE", Path(folder) / "scenarios.json"),
            patch("web_control.test_finance_tools.uk_today", return_value=TODAY),
            patch(
                "web_control.test_finance_tools.collect",
                side_effect=AssertionError("Bank lookup"),
            ),
            patch("finance.receipt.load_finance_settings", return_value={}),
            patch("finance.savings_targets.load_view", return_value=[]),
            patch("web_control.test_finance_tools.payment_options", return_value=[]),
            patch(
                "web_control.test_finance_tools.render_template", return_value="ok"
            ) as render,
        ):
            client = app.test_client()
            response = client.post(
                "/finance/test/scenarios/save",
                data=dict(values(), scenario_name="Plan"),
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.get(response.headers["Location"]).status_code, 200)
            self.assertEqual(render.call_args.kwargs["values"]["salary"], "1000")
            self.assertEqual(render.call_args.kwargs["preset_name"], "Plan")
            self.assertIsNone(render.call_args.kwargs["result_text"])
            self.assertIsNone(render.call_args.kwargs["scenario_details"])
            start_print.assert_not_called()


class TransferExplanationTests(TestCase):
    def test_explanation_uses_existing_allocation_and_accounts_for_cash_once(self):
        result = build(base(), values(), TODAY)
        before = deepcopy(result)
        explanation = explain(result)
        first = result["forecast"]["payments"][0]
        rows = {row["label"]: row["amount"] for row in explanation["rows"]}
        self.assertEqual(rows["Still needed for HSBC / Monzo / Cash targets"], "£1,000.00")
        self.assertEqual(rows["Spare bank cash used for extra transfers"], "£1,200.00")
        self.assertEqual(rows["Extra savings transfers"], "£0.00")
        self.assertEqual(
            first["opening"]
            - result["projection"]["buffer"]
            - first["costs"]
            - first["variable"]
            - first["extra"]
            - first["savings"],
            first["cash_after_allocation"],
        )
        self.assertEqual(result, before)
        self.assertEqual(len(explanation["destinations"]), 1)
        self.assertIn("Amex", explanation["destinations"][0]["name"])

    def test_no_salary_can_repay_debt_while_investments_remain_paused(self):
        result = build(base(), values(salary="0", other_income="1000"), TODAY)
        explanation = explain(result)
        self.assertFalse(explanation["salary_active"])
        self.assertEqual(
            next(
                row["amount"]
                for row in explanation["rows"]
                if row["label"] == "Spare bank cash used for extra transfers"
            ),
            "£1,200.00",
        )
        self.assertGreater(result["forecast"]["payments"][0]["extra"], 0)

    def test_shortfall_is_explicit_and_protected_cash_is_separate(self):
        source = base()
        source["reserve_details"] = {"gap": D(280), "tax_reserve": D(100)}
        source["buffer"] = D(1380)
        result = build(source, values(salary="0"), TODAY)
        explanation = explain(result)
        self.assertTrue(explanation["funded"])
        self.assertIsNotNone(result["forecast"]["run_out"])
        rows = {row["label"]: row["amount"] for row in explanation["rows"]}
        self.assertEqual(rows["Other protected reserves"], "£100.00")
        self.assertEqual(rows["Still needed for HSBC / Monzo / Cash targets"], "£1,280.00")


class VersionedRecordsTests(TestCase):
    def test_savings_read_migrates_without_rewriting_and_edit_versions_file(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(savings_goals, "FILE", Path(folder) / "goals.json"),
        ):
            original = '{"accounts":{},"entries":[],"years":{}}'
            savings_goals.FILE.write_text(original)
            self.assertEqual(savings_goals.load()["schema_version"], 1)
            self.assertEqual(savings_goals.FILE.read_text(), original)
            with savings_goals.edit() as state:
                state["years"]["2026"] = {"complete": False}
            self.assertEqual(
                json.loads(savings_goals.FILE.read_text())["schema_version"], 1
            )
            state["schema_version"] = 2
            savings_goals.FILE.write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                savings_goals.load()

    def test_archive_metadata_is_private_fingerprints_and_older_receipts_load(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(archive, "DIRECTORY", Path(folder)),
            patch.object(
                build_info, "application_version", return_value="test-revision"
            ),
            patch.object(
                settings,
                "settings_state",
                return_value=(deepcopy(settings.DEFAULT_SETTINGS), None),
            ),
        ):
            identifier = archive.save(
                {"finance": "receipt"},
                {},
                "2026-10-12T12:00:00+00:00",
                "preview",
                {},
                test_finance={"values": {"salary": "1000"}},
            )
            item = archive.load(identifier)
            self.assertEqual(item["schema_version"], 1)
            self.assertEqual(item["build"]["application_version"], "test-revision")
            self.assertEqual(len(item["build"]["scenario_fingerprint"]), 64)
            self.assertNotIn("Stirchley", json.dumps(item["build"]))
            del item["schema_version"]
            del item["build"]
            (archive.DIRECTORY / (identifier + ".json")).write_text(json.dumps(item))
            self.assertEqual(archive.load(identifier)["pages"], {"finance": "receipt"})

    def test_backup_validation_uses_version_and_settings_validators(self):
        from web_control.private_backup import _validate_file

        _validate_file(
            "receipt_settings.last-good.json", {"features": {"weather": False}}
        )
        with self.assertRaises(ValueError):
            _validate_file(
                "savings_goals.json",
                {"schema_version": 2, "accounts": {}, "entries": [], "years": {}},
            )
        with self.assertRaises(ValueError):
            _validate_file("receipt_settings.json", {"features": {"weather": "false"}})
