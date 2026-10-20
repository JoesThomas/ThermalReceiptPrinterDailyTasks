from receipt.profile import COLUMNS
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import os
import subprocess
from finance import named_comparison
from web_control import attention, printer_test_job, print_job, test_finance_tools
from deployment import update_helper as updates
from storage import write_json

TODAY = date(2026, 10, 13)


def inputs(**changes):
    return dict(
        dict(
            salary="1000",
            start=str(TODAY),
            months="2",
            strategy="amex_first",
            save_all="on",
            opening_cash="1200",
            daily_spend="10",
            amex_owed="500",
        ),
        **changes,
    )


class PaperTestTests(TestCase):
    def test_paper_test_prints_only_small_ascii_and_one_cut(self):
        printer = Mock()
        with (
            patch.object(
                printer_test_job, "open_printer", return_value=printer
            ) as opening,
            patch.object(printer_test_job.sys, "argv", ["worker", "--paper-test"]),
        ):
            printer_test_job.main()
        opening.assert_called_once_with(initial_cut=False)
        text = "".join(call.args[0] for call in printer.text.call_args_list)
        self.assertEqual(len(text.splitlines()), 12)
        self.assertIn("PAPER REFILL TEST", text)
        self.assertIn(" (____).__|", text)
        self.assertTrue(all(len(line) <= COLUMNS for line in text.splitlines()))
        printer.cut.assert_called_once()
        printer.close.assert_called_once()

    def test_tests_identify_connection_and_london_timestamp(self):
        for args, heading, connection, method, when, stamp in (
            (
                ["--paper-test"],
                "PAPER REFILL TEST",
                " NETWORK ",
                "Network (TCP)",
                datetime(2026, 10, 13, 20, 30, 46, tzinfo=timezone.utc),
                "13 Oct 2026 21:30:46 BST",
            ),
            (
                [],
                "PRINTER CONNECTION TEST",
                " USB ",
                "USB",
                datetime(2026, 1, 13, 20, 30, 46, tzinfo=timezone.utc),
                "13 Jan 2026 20:30:46 GMT",
            ),
        ):
            with self.subTest(connection=connection):
                printer = Mock()
                with (
                    patch.object(
                        printer_test_job, "open_printer", return_value=printer
                    ),
                    patch.object(printer_test_job.sys, "argv", ["worker", *args]),
                    patch.dict(os.environ, {"RECEIPT_PRINTER_CONNECTION": connection}),
                    patch.object(printer_test_job, "datetime") as clock,
                ):
                    clock.now.side_effect = lambda zone: when.astimezone(zone)
                    printer_test_job.main()
                text = "".join(call.args[0] for call in printer.text.call_args_list)
                self.assertIn(heading, text)
                self.assertIn(stamp, text)
                self.assertIn(f"Connection: {method}", text)
                self.assertIn("Check print is clear and paper is cut.", text)
                self.assertTrue(all(len(line) <= COLUMNS for line in text.splitlines()))
                printer.cut.assert_called_once()
                printer.close.assert_called_once()

    def test_paper_test_uses_worker_without_receipt_collection(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / "lock"
            lock.write_text(str(os.getpid()))
            with (
                patch.object(print_job, "ROOT", root),
                patch.object(print_job, "LOCK", lock),
                patch.object(print_job, "STATUS", root / "status.json"),
                patch.object(print_job, "run_bounded", return_value=0) as run,
                patch.object(print_job.sys, "argv", ["worker", "--paper-test"]),
            ):
                self.assertEqual(print_job.main(), 0)
            self.assertTrue(run.call_args.args[0][-2].endswith("printer_test_job.py"))
            self.assertEqual(run.call_args.args[0][-1], "--paper-test")
            self.assertFalse(lock.exists())


class AttentionTests(TestCase):
    def test_saved_state_only_and_bank_snapshot_is_not_read(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
            write_json(root / "data" / "printer_diagnostics.json", {"reachable": False})
            write_json(
                root / "cache" / "finance_review" / "status.json",
                {"state": "failed", "stage": "SECRET"},
            )
            write_json(
                root / "data" / "api_health.json",
                {
                    "services": {
                        "Weather": {"status": "failed"},
                        "SECRET": {"status": "failed"},
                    }
                },
            )
            with patch(
                "services.bank_session.collect_snapshot",
                side_effect=AssertionError("bank lookup"),
            ):
                items = attention.build(
                    root,
                    {"print_schedule": {"enabled": False, "time": "03:00"}},
                    now=now,
                    warning="damaged",
                )
            self.assertEqual(
                {item["id"] for item in items},
                {"settings", "printer", "bank", "integrations"},
            )
            self.assertNotIn("SECRET", str(items))
            self.assertFalse(
                (root / "cache" / "finance_review" / "snapshot.json").exists()
            )

    def test_partial_stale_and_delayed_sources_have_actions(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
            write_json(
                root / "cache" / "finance_review" / "status.json",
                {"state": "completed", "coverage": "partial"},
            )
            write_json(
                root / "data" / "source_cache.json",
                {"id": {"name": "Calendar", "next_retry_epoch": now.timestamp() + 60}},
            )
            settings = {"print_schedule": {"enabled": False, "time": "03:00"}}
            self.assertEqual(
                {row["id"] for row in attention.build(root, settings, now=now)},
                {"bank-partial", "integrations"},
            )
            write_json(
                root / "cache" / "finance_review" / "status.json",
                {
                    "state": "completed",
                    "checked_at": (now - timedelta(hours=1)).isoformat(),
                },
            )
            self.assertIn(
                "bank-stale",
                {row["id"] for row in attention.build(root, settings, now=now)},
            )

    def test_retry_summary_avoids_reading_large_source_payloads(self):
        from services import source_cache

        with TemporaryDirectory() as folder:
            root = Path(folder)
            now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
            with patch.object(
                source_cache, "FILE", root / "data" / "source_cache.json"
            ):
                source_cache.record(
                    "hash",
                    {
                        "name": "Calendar",
                        "result": ["x" * 200000],
                        "next_retry_epoch": now.timestamp() + 60,
                        "attempted_at": now.isoformat(),
                    },
                )
            read = attention.read

            def small_only(path):
                if path.name == "source_cache.json":
                    self.fail("Full source payload was read")
                return read(path)

            with patch.object(attention, "read", side_effect=small_only):
                items = attention.build(
                    root,
                    {"print_schedule": {"enabled": False, "time": "03:00"}},
                    now=now,
                )
            self.assertEqual(items[0]["id"], "integrations")
            self.assertLess(
                (root / "data" / "source_retry_status.json").stat().st_size, 1000
            )


class NamedComparisonTests(TestCase):
    def local(self):
        return {
            "settings": {"debts": [{"name": "Amex", "balance": "500"}]},
            "subscriptions": {"monthly": [], "yearly": [], "instalments": []},
            "accounts": [],
        }

    def test_manual_overrides_and_debt_reserves_match_separate_forecasts(self):
        left = {"name": "First", "values": inputs()}
        right = {
            "name": "Second",
            "values": inputs(
                opening_cash="2400",
                daily_spend="5",
                amex_owed="1000",
                strategy="savings_first",
            ),
        }
        local = self.local()
        before = deepcopy(local)
        with (
            patch(
                "finance.receipt.load_finance_settings", return_value=local["settings"]
            ),
            patch(
                "services.subscriptions.load_subscriptions",
                return_value=local["subscriptions"],
            ),
            patch("finance.savings_targets.load_view", return_value=[]),
            patch.object(
                test_finance_tools,
                "bank_snapshot",
                side_effect=AssertionError("manual bank lookup"),
            ),
        ):
            comparison = named_comparison.compare(
                left, right, TODAY, test_finance_tools.collect_pair
            )
            projections = [
                test_finance_tools.collect(row["values"], TODAY)
                for row in (left, right)
            ]
        from finance.scenario_plan import build
        from finance.test_scenarios import snapshot

        for row, projection, result in zip(
            (left, right), projections, comparison["results"]
        ):
            expected = snapshot(build(projection, row["values"], TODAY), TODAY)
            self.assertEqual(result["savings_end"], expected["savings_end"])
            self.assertEqual(result["minimum_bank"], expected["minimum_bank"])
            self.assertEqual(result["amex_end"], expected["amex_end"])
        self.assertEqual(local, before)
        self.assertTrue(comparison["manual"])
        self.assertIn(
            "Starting bank cash", [row["label"] for row in comparison["differences"]]
        )

    def test_live_comparison_fetches_once_and_reuses_same_snapshot(self):
        local = self.local()
        snapshot = {
            "data": [[], [], [], [], {"bank_data_status": "complete"}],
            "balances": {
                "HSBC": {"available": D(2200)},
                "MONZO": {"available": D(0)},
                "AMEX": {"current": D(500)},
            },
        }
        pipeline = SimpleNamespace(
            build_subscription_status=lambda transactions, **kwargs: {
                "monthly": [],
                "yearly": [],
            }
        )
        with (
            patch.dict("sys.modules", {"services.live_pipeline": pipeline}),
            patch.object(
                test_finance_tools, "bank_snapshot", return_value=snapshot
            ) as lookup,
            patch(
                "finance.receipt.load_finance_settings", return_value=local["settings"]
            ),
            patch(
                "services.subscriptions.load_subscriptions",
                return_value=local["subscriptions"],
            ),
            patch("finance.savings_targets.load_view", return_value=[]),
        ):
            plans = test_finance_tools.collect_pair(
                [
                    inputs(opening_cash="", daily_spend=""),
                    inputs(opening_cash="", daily_spend="", salary="2000"),
                ],
                TODAY,
            )
        lookup.assert_called_once_with(TODAY)
        self.assertEqual(plans[0]["cash"], plans[1]["cash"])
        self.assertEqual(plans[0]["amex"]["balance"], plans[1]["amex"]["balance"])

    def test_old_dates_fail_before_collection_and_do_not_mutate_saved_inputs(self):
        left = {"name": "Old", "values": inputs(start="2026-10-12")}
        right = {"name": "Current", "values": inputs()}
        collect = Mock()
        with self.assertRaisesRegex(ValueError, "Old:"):
            named_comparison.compare(left, right, TODAY, collect)
        collect.assert_not_called()
        self.assertEqual(left["values"]["start"], "2026-10-12")


class UpdateHelperTests(TestCase):
    def repository(self, folder):
        root = Path(folder) / "project"
        root.mkdir()

        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=root, check=True, capture_output=True
            ).stdout

        git("init")
        git("config", "user.email", "tests@example.invalid")
        git("config", "user.name", "Tests")
        (root / ".gitignore").write_text("data/\n.venv\n.venv-next-*\n")
        (root / "code.txt").write_text("old")
        git("add", ".")
        git("commit", "-m", "old")
        old = updates.revision(root)
        (root / "code.txt").write_text("new")
        git("commit", "-am", "new")
        new = updates.revision(root)
        git("checkout", "--detach", old)
        (root / ".venv").mkdir()
        (root / ".venv" / "identity").write_text("old env")
        write_json(
            root / "data" / "receipt_settings.json", {"features": {"weather": False}}
        )
        return root, old, new

    def prepare(self, root, target, validator=None):
        state = updates.prepare(
            root, target, install=False, validate=validator or Mock()
        )
        env = updates.environment(root, state["id"])
        env.mkdir(parents=True)
        (env / "identity").write_text("new env")
        return state

    def test_prepare_does_not_change_live_code_settings_or_environment(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            settings = (root / "data" / "receipt_settings.json").read_bytes()
            state = self.prepare(root, new)
            self.assertEqual(updates.revision(root), old)
            self.assertEqual((root / ".venv" / "identity").read_text(), "old env")
            self.assertEqual(
                (root / "data" / "receipt_settings.json").read_bytes(), settings
            )
            self.assertEqual(state["phase"], "prepared")
            self.assertEqual(
                (updates.directory(root, state["id"]) / "state.json").stat().st_mode
                & 0o777,
                0o600,
            )

    def test_apply_then_rollback_preserves_new_settings_by_default(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            updates.apply(root, state["id"], stopped=True, validate=Mock())
            self.assertEqual(updates.revision(root), new)
            self.assertTrue((root / ".venv").is_symlink())
            write_json(
                root / "data" / "receipt_settings.json", {"features": {"weather": True}}
            )
            updates.rollback(root, state["id"], stopped=True, validate=Mock())
            self.assertEqual(updates.revision(root), old)
            self.assertFalse((root / ".venv").is_symlink())
            self.assertIn("true", (root / "data" / "receipt_settings.json").read_text())
            self.assertEqual((root / ".venv" / "identity").read_text(), "old env")

    def test_explicit_settings_restore_retains_current_checkpoint_and_original_absence(
        self,
    ):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            updates.apply(root, state["id"], stopped=True, validate=Mock())
            write_json(
                root / "data" / "receipt_settings.json", {"features": {"weather": True}}
            )
            write_json(root / "data" / "savings.json", {"accounts": []})
            updates.rollback(
                root, state["id"], stopped=True, restore_settings=True, validate=Mock()
            )
            self.assertIn(
                "false", (root / "data" / "receipt_settings.json").read_text()
            )
            self.assertFalse((root / "data" / "savings.json").exists())
            self.assertTrue(
                (updates.directory(root, state["id"]) / "before-rollback.json").exists()
            )

    def test_failed_activation_restores_checkout_and_existing_environment(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            original = updates.switch_environment

            def fail(*args):
                original(*args)
                raise OSError("test failure")

            with (
                patch.object(updates, "switch_environment", side_effect=fail),
                self.assertRaises(OSError),
            ):
                updates.apply(root, state["id"], stopped=True, validate=Mock())
            self.assertEqual(updates.revision(root), old)
            self.assertEqual((root / ".venv" / "identity").read_text(), "old env")
            self.assertEqual(
                updates.read_state(root, state["id"])["phase"], "rolled_back"
            )

    def test_dirty_checkout_changed_candidate_and_missing_stop_are_refused(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            with self.assertRaisesRegex(ValueError, "Stop the web app"):
                updates.apply(root, state["id"], validate=Mock())
            self.assertEqual(updates.revision(root), old)
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            (root / "code.txt").write_text("my edits")
            with self.assertRaisesRegex(ValueError, "local changes"):
                updates.prepare(root, new, install=False, validate=Mock())
            self.assertEqual((root / "code.txt").read_text(), "my edits")

    def test_candidate_edits_and_stale_preparation_are_refused(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            (
                updates.directory(root, state["id"]) / "candidate" / "code.txt"
            ).write_text("changed")
            with self.assertRaisesRegex(ValueError, "local changes"):
                updates.apply(root, state["id"], stopped=True, validate=Mock())
            self.assertEqual(updates.revision(root), old)

    def test_environment_switch_failure_after_move_recovers_original_directory(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            original = Path.symlink_to

            def fail(path, *args, **kwargs):
                if path.name.startswith(".venv-next-"):
                    raise OSError("link error")
                return original(path, *args, **kwargs)

            with patch.object(Path, "symlink_to", fail), self.assertRaises(OSError):
                updates.apply(root, state["id"], stopped=True, validate=Mock())
            self.assertEqual((root / ".venv" / "identity").read_text(), "old env")
            self.assertEqual(updates.revision(root), old)

    def test_failed_rollback_returns_to_applied_code_and_current_settings(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            updates.apply(root, state["id"], stopped=True, validate=Mock())
            write_json(
                root / "data" / "receipt_settings.json", {"features": {"weather": True}}
            )
            original = updates.restore
            calls = []

            def fail_once(*args):
                calls.append(1)
                if len(calls) == 1:
                    raise OSError("restore failure")
                return original(*args)

            with (
                patch.object(updates, "restore", side_effect=fail_once),
                self.assertRaises(OSError),
            ):
                updates.rollback(
                    root,
                    state["id"],
                    stopped=True,
                    restore_settings=True,
                    validate=Mock(),
                )
            self.assertEqual(updates.revision(root), new)
            self.assertEqual((root / ".venv" / "identity").read_text(), "new env")
            self.assertIn("true", (root / "data" / "receipt_settings.json").read_text())

    def test_incomplete_checkpoint_is_refused_before_service_or_checkout_changes(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            state = self.prepare(root, new)
            write_json(
                updates.directory(root, state["id"]) / "state.json",
                {"format": 1, "id": state["id"], "target": new},
            )
            with (
                patch.object(updates, "service") as service,
                self.assertRaises(ValueError),
            ):
                updates.apply(root, state["id"], manage_service=True, validate=Mock())
            service.assert_not_called()
            self.assertEqual(updates.revision(root), old)

    def test_validation_failure_never_activates_candidate(self):
        with TemporaryDirectory() as folder:
            root, old, new = self.repository(folder)
            with self.assertRaises(ValueError):
                updates.prepare(
                    root,
                    new,
                    install=False,
                    validate=Mock(side_effect=ValueError("schema")),
                )
            self.assertEqual(updates.revision(root), old)
            self.assertEqual((root / ".venv" / "identity").read_text(), "old env")
