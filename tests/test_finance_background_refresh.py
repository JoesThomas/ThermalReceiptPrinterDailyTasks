from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from web_control.finance_refresh import FinanceRefresh, encode, decode
from storage import write_json


def snapshot(coverage="complete"):
    return {
        "data": (
            [{"date": "2026-10-11", "amount": -10}],
            [],
            [],
            [],
            {
                "bank_data_status": coverage,
                "salary_incomings": [
                    {"date": date(2026, 10, 11), "amount": Decimal("1.01")}
                ],
            },
        ),
        "balances": {"HSBC": {"available": 100}, "MONZO": {"available": 0}},
    }


class FinanceBackgroundTests(TestCase):
    def test_refresh_returns_without_bank_wait_and_coalesces_across_managers(self):
        with TemporaryDirectory() as folder:
            entered = Event()
            release = Event()
            calls = []

            def collect(progress):
                calls.append(1)
                progress("Retrieving HSBC transactions")
                entered.set()
                if not release.wait(3):
                    raise TimeoutError()
                return snapshot()

            manager = FinanceRefresh(folder, collect)
            other = FinanceRefresh(folder, collect)
            try:
                self.assertTrue(manager.start())
                self.assertTrue(entered.wait(1))
                self.assertFalse(manager.start())
                other.start()
                other.worker.join(1)
                self.assertEqual(calls, [1])
                self.assertEqual(other.status()["state"], "running")
                self.assertIn("HSBC", manager.public_status()["stage"])
                self.assertIsNone(manager.read())
            finally:
                release.set()
                manager.worker.join(3)
            result = manager.read()
            self.assertEqual(
                result["data"][4]["salary_incomings"][0]["date"], date(2026, 10, 11)
            )
            self.assertEqual(
                result["data"][4]["salary_incomings"][0]["amount"], Decimal("1.01")
            )
            self.assertTrue(manager.fresh(result))
            self.assertEqual(manager.status()["state"], "completed")
            self.assertEqual(manager.snapshot_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(manager.directory.stat().st_mode & 0o777, 0o700)

    def test_failed_refresh_preserves_snapshot_and_withholds_freshness(self):
        with TemporaryDirectory() as folder:
            manager = FinanceRefresh(folder, lambda progress: snapshot())
            manager.start()
            manager.worker.join(3)
            before = manager.snapshot_file.read_bytes()

            def fail(progress):
                raise ValueError("private account secret")

            manager.collect = fail
            manager.start(force=True)
            manager.worker.join(3)
            self.assertEqual(manager.snapshot_file.read_bytes(), before)
            self.assertEqual(manager.status()["state"], "failed")
            self.assertFalse(manager.fresh(manager.read()))
            self.assertNotIn("private account secret", manager.status_file.read_text())
            self.assertFalse(
                manager.start()
            )  # Avoid an immediate automatic retry loop.

    def test_old_future_and_new_scope_snapshots_are_not_fresh(self):
        with TemporaryDirectory() as folder:
            manager = FinanceRefresh(folder, lambda progress: snapshot("partial"))
            manager.start()
            manager.worker.join(3)
            value = manager.read()
            self.assertEqual(value["data"][4]["bank_data_status"], "partial")
            for minutes in (-31, 5):
                old = dict(
                    value,
                    checked_at=(
                        datetime.now(timezone.utc) + timedelta(minutes=minutes)
                    ).isoformat(),
                )
                self.assertFalse(manager.fresh(old))
            write_json(
                Path(folder) / "data" / "transaction_sources.json", {"monzo": "all"}
            )
            self.assertIsNone(manager.read())

    def test_source_change_during_refresh_never_publishes_wrong_scope(self):
        with TemporaryDirectory() as folder:

            def collect(progress):
                write_json(
                    Path(folder) / "data" / "bank_account_selection.json",
                    {"HSBC": ["changed"]},
                )
                return snapshot()

            manager = FinanceRefresh(folder, collect)
            manager.start()
            manager.worker.join(3)
            self.assertEqual(manager.status()["state"], "failed")
            self.assertIsNone(manager.read())

    def test_abandoned_running_status_and_corrupt_cache_are_recoverable(self):
        with TemporaryDirectory() as folder:
            manager = FinanceRefresh(folder)
            write_json(
                manager.status_file,
                {
                    "state": "running",
                    "started_at": (
                        datetime.now(timezone.utc) - timedelta(hours=1)
                    ).isoformat(),
                },
            )
            self.assertEqual(manager.status()["state"], "failed")
            write_json(
                manager.snapshot_file,
                {"version": 1, "scope": manager.scope(), "checked_at": "invalid"},
            )
            self.assertIsNone(manager.read())

    def test_status_polling_never_reads_the_transaction_snapshot(self):
        with TemporaryDirectory() as folder:
            manager = FinanceRefresh(folder, lambda progress: snapshot())
            manager.start()
            manager.worker.join(3)
            with patch.object(
                manager,
                "read",
                side_effect=AssertionError("Payload read during status polling"),
            ):
                status = manager.public_status()
            self.assertTrue(status["fresh"])
            self.assertIsNotNone(status["checked_at"])
            self.assertNotIn("scope", status)
            self.assertFalse(manager.fresh({"checked_at": "bad timestamp"}))

    def test_snapshot_codec_preserves_money_and_dates_without_credentials(self):
        value = {
            "date": date(2026, 10, 11),
            "amount": Decimal("0.01"),
            "now": datetime.now(timezone.utc),
        }
        self.assertEqual(decode(encode(value)), value)
