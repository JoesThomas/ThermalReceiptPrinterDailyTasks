from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import os
import subprocess
from receipt import printer_status
from services import source_cache, api_health
from services.retry_policy import delay
from web_control import schedule_history, scheduled_print, print_job
from tools import pi_acceptance
from storage import file_lock


class SourceRetryTests(TestCase):
    def test_repeated_failure_delays_without_extending_saved_data_age(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(source_cache, "FILE", Path(folder) / "cache.json"),
            patch("receipt.freshness.mark") as mark,
            patch.object(source_cache.time, "time", return_value=1000),
        ):
            source_cache.get("Weather", "location", lambda: ["old"])
            failure = Mock(side_effect=TimeoutError("PRIVATE"))
            with patch.object(source_cache.time, "time", return_value=1400):
                self.assertEqual(
                    source_cache.get("Weather", "location", failure), ["old"]
                )
                self.assertEqual(
                    source_cache.get("Weather", "location", failure), ["old"]
                )
                self.assertEqual(
                    source_cache.get("Weather", "location", failure), ["old"]
                )
                self.assertEqual(failure.call_count, 2)
                row = next(iter(source_cache.load().values()))
                self.assertEqual(row["saved_epoch"], 1000)
                self.assertEqual(row["next_retry_epoch"], 1460)
                self.assertEqual(mark.call_args.args[1], "cached during retry delay")
                self.assertTrue(mark.call_args.kwargs["source_checked_at"])
                self.assertNotIn("PRIVATE", source_cache.FILE.read_text())
                source_cache.refresh()
                self.assertEqual(
                    source_cache.get("Weather", "location", lambda: ["new"]), ["new"]
                )
                row = next(iter(source_cache.load().values()))
                self.assertEqual(row["failures"], 0)
                self.assertEqual(row["next_retry_epoch"], 0)

    def test_expired_cache_stays_unavailable_during_delay_and_manual_retry_bypasses(
        self,
    ):
        with (
            TemporaryDirectory() as folder,
            patch.object(source_cache, "FILE", Path(folder) / "cache.json"),
            patch("receipt.freshness.mark"),
            patch.object(source_cache.time, "time", return_value=1000),
        ):
            failure = Mock(side_effect=TimeoutError())
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    source_cache.get("Calendar", "day", failure)
            with self.assertRaises(source_cache.SourceBackoffError):
                source_cache.get("Calendar", "day", failure)
            self.assertEqual(failure.call_count, 2)
            with patch.dict(os.environ, {"RECEIPT_REFRESH_SOURCE": "Calendar"}):
                self.assertEqual(
                    source_cache.get("Calendar", "day", lambda: ["manual"]), ["manual"]
                )
            with patch.object(source_cache.time, "time", return_value=90000):
                with self.assertRaises(TimeoutError):
                    source_cache.get("Calendar", "day", failure)

    def test_delay_is_bounded_and_partial_results_do_not_reset_failure_counter(self):
        self.assertEqual([delay(i) for i in (0, 1, 2, 3, 100)], [0, 0, 60, 120, 3600])
        with (
            TemporaryDirectory() as folder,
            patch.object(source_cache, "FILE", Path(folder) / "cache.json"),
            patch("receipt.freshness.mark"),
            patch.object(source_cache.time, "time", return_value=1000),
        ):
            partial = Mock(return_value=([], "partial"))
            source_cache.get("Deliveries", "day", partial, ttl=0)
            source_cache.get("Deliveries", "day", partial, ttl=0)
            source_cache.get("Deliveries", "day", partial, ttl=0)
            self.assertEqual(partial.call_count, 2)
            self.assertEqual(next(iter(source_cache.load().values()))["failures"], 2)

    def test_health_delay_skips_automatic_probe_but_allows_manual_after_cooldown(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.object(api_health, "ROOT", root),
                patch.object(api_health, "FILE", root / "data" / "health.json"),
                patch.object(api_health, "RUN_LOCK", root / "data" / "probe.lock"),
                patch.object(api_health, "receipt_busy", return_value=False),
                patch.object(
                    api_health,
                    "options",
                    return_value={"enabled": True, "interval_minutes": 15},
                ),
                patch.object(
                    api_health,
                    "specifications",
                    return_value=[("Weather", "url", None, "weather")],
                ),
            ):
                api_health.record("Weather", "failed", mode="active")
                api_health.record("Weather", "failed", mode="active")
                row = api_health.load()["services"]["Weather"]
                self.assertTrue(api_health.retry_pending(row["next_retry_at"]))
                with patch.object(api_health, "probe") as probe:
                    self.assertTrue(api_health.check_once())
                    probe.assert_not_called()
                    # A single-source manual attempt is still rate-limited for 30 seconds.
                    self.assertTrue(
                        api_health.check_once(force=True, service="Weather")
                    )
                    probe.assert_not_called()
                    with api_health.transaction() as state:
                        state["services"]["Weather"]["last_probe_at"] = (
                            datetime.now(timezone.utc) - timedelta(seconds=31)
                        ).isoformat()
                    self.assertTrue(
                        api_health.check_once(force=True, service="Weather")
                    )
                    probe.assert_called_once()
                api_health.record("Weather", "healthy", mode="active")
                self.assertIsNone(
                    api_health.load()["services"]["Weather"]["next_retry_at"]
                )


class DailyOutcomeTests(TestCase):
    def test_fast_worker_outcome_is_not_replaced_by_parent_launch(self):
        with TemporaryDirectory() as folder:
            marker = Path(folder) / "last"
            on = date(2026, 10, 12)

            def start(args):
                schedule_history.record(on, "sent", directory=marker.parent)
                return True, ""

            self.assertTrue(scheduled_print.print_once(on, start, marker))
            self.assertEqual(
                schedule_history.store(folder).read()["days"][str(on)]["state"], "sent"
            )
            self.assertTrue(
                scheduled_print.print_once(
                    on, lambda args: self.fail("Duplicate launch"), marker
                )
            )

    def test_launch_failure_is_recorded_and_can_retry_without_marker(self):
        with TemporaryDirectory() as folder:
            marker = Path(folder) / "last"
            on = date(2026, 10, 12)
            self.assertFalse(
                scheduled_print.print_once(on, lambda args: (False, "busy"), marker)
            )
            self.assertFalse(marker.exists())
            self.assertEqual(
                schedule_history.store(folder).read()["days"][str(on)]["state"],
                "launch_failed",
            )
            self.assertTrue(
                scheduled_print.print_once(on, lambda args: (True, ""), marker)
            )

    def test_missing_and_legacy_days_are_reported_without_writing_on_read(self):
        with TemporaryDirectory() as folder:
            settings = {"print_schedule": {"enabled": True, "time": "03:00"}}
            now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
            self.assertEqual(
                schedule_history.summary(settings, now=now, directory=folder)["today"][
                    "state"
                ],
                "missed",
            )
            self.assertFalse(list(Path(folder).glob("*.json")))
            (Path(folder) / ".scheduled_print_date").write_text("2026-10-12")
            self.assertEqual(
                schedule_history.summary(settings, now=now, directory=folder)["today"][
                    "state"
                ],
                "legacy",
            )

    def test_interrupted_worker_and_bounded_history(self):
        with TemporaryDirectory() as folder:
            on = date(2026, 10, 12)
            schedule_history.record(on, "running", directory=folder, worker_pid=12345)
            with patch.object(
                schedule_history.os, "kill", side_effect=ProcessLookupError
            ):
                row = schedule_history.summary(
                    {"print_schedule": {"enabled": True, "time": "03:00"}},
                    now=datetime.now(timezone.utc),
                    directory=folder,
                )["recent"][0]
                self.assertEqual(row["state"], "interrupted")
            for offset in range(100):
                schedule_history.record(
                    on - timedelta(days=offset), "sent", directory=folder
                )
            self.assertEqual(len(schedule_history.store(folder).read()["days"]), 90)

    def test_scheduled_worker_records_saved_preview_on_offline_printer(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            status = root / "status.json"
            lock = root / "lock"
            lock.write_text(str(os.getpid()))
            with (
                patch.object(print_job, "ROOT", root),
                patch.object(print_job, "STATUS", status),
                patch.object(print_job, "LOCK", lock),
                patch.object(print_job, "run_bounded", return_value=0),
                patch("receipt.lifestyle.active", return_value=False),
                patch("receipt.printer.readiness", return_value=(False, "offline")),
                patch.object(print_job.sys, "argv", ["worker", "--scheduled"]),
            ):
                self.assertEqual(print_job.main(), 1)
            row = next(
                iter(schedule_history.store(root / "data").read()["days"].values())
            )
            self.assertEqual(row["state"], "failed")
            self.assertTrue(row["preview_saved"])
            self.assertFalse(lock.exists())

    def test_scheduled_worker_sent_timeout_cancelled_and_away_outcomes(self):
        from web_control.job_runtime import JobCancelled

        for outcome, result, away in [
            ("sent", 0, False),
            ("timed_out", subprocess.TimeoutExpired("worker", 600), False),
            ("cancelled", JobCancelled(), False),
            ("saved_preview", 0, True),
        ]:
            with self.subTest(outcome=outcome), TemporaryDirectory() as folder:
                root = Path(folder)
                status = root / "status.json"
                lock = root / "lock"
                lock.write_text(str(os.getpid()))
                with (
                    patch.object(print_job, "ROOT", root),
                    patch.object(print_job, "STATUS", status),
                    patch.object(print_job, "LOCK", lock),
                    patch.object(
                        print_job,
                        "run_bounded",
                        side_effect=result if isinstance(result, Exception) else None,
                        return_value=result,
                    ),
                    patch("receipt.lifestyle.active", return_value=away),
                    patch("receipt.printer.readiness", return_value=(True, "online")),
                    patch.object(print_job.sys, "argv", ["worker", "--scheduled"]),
                ):
                    print_job.main()
                self.assertEqual(
                    next(
                        iter(
                            schedule_history.store(root / "data")
                            .read()["days"]
                            .values()
                        )
                    )["state"],
                    outcome,
                )
                self.assertFalse(lock.exists())

    def test_day_history_prevents_retry_when_marker_write_fails_after_launch(self):
        with TemporaryDirectory() as folder:
            marker = Path(folder) / "last"
            on = date(2026, 10, 12)
            start = Mock(return_value=(True, ""))
            from storage import write_bytes

            def write(path, content):
                if Path(path) == marker:
                    raise OSError("marker lost")
                return write_bytes(path, content)

            with patch("storage.write_bytes", side_effect=write):
                with self.assertRaises(OSError):
                    scheduled_print.print_once(on, start, marker)
            self.assertEqual(start.call_count, 1)
            self.assertFalse(marker.exists())
            self.assertTrue(scheduled_print.print_once(on, start, marker))
            self.assertEqual(start.call_count, 1)

    def test_two_scheduler_processes_only_launch_one_job(self):
        import multiprocessing

        with TemporaryDirectory() as folder:
            marker = Path(folder) / "last"
            counter = Path(folder) / "count"
            on = date(2026, 10, 12)

            def worker():
                def start(args):
                    with counter.open("a") as stream:
                        stream.write("launch\n")
                    return True, ""

                scheduled_print.print_once(on, start, marker)

            context = multiprocessing.get_context("fork")
            workers = [context.Process(target=worker) for _ in range(2)]
            for process in workers:
                process.start()
            for process in workers:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join()
                    self.fail("Scheduler process did not finish")
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(counter.read_text().splitlines(), ["launch"])

    def test_worker_matches_parent_day_across_midnight(self):
        with TemporaryDirectory() as folder:
            now = datetime.now(timezone.utc)
            parent_day = (now - timedelta(days=1)).date()
            schedule_history.record(parent_day, "starting", directory=folder)
            self.assertEqual(
                schedule_history.pending_day(folder, now=now + timedelta(seconds=1)),
                parent_day,
            )


class PrinterSensorTests(TestCase):
    def test_sensor_masks_validate_and_open_cover_suppresses_old_paper_reading(self):
        self.assertEqual(printer_status.decode(b"\x12", b"\x12")["paper"], "present")
        self.assertEqual(printer_status.decode(b"\x12", b"\x72")["paper"], "out")
        opened = printer_status.decode(b"\x16", b"\x12")
        self.assertEqual(opened["cover"], "open")
        self.assertEqual(opened["paper"], "unknown")
        for invalid in (b"", b"\x00", b"\xff", b"\x12\x12"):
            self.assertEqual(
                printer_status.decode(invalid, b"\x12")["cover"], "unknown"
            )
        self.assertEqual(printer_status.decode(b"\x12", b"\x32")["paper"], "unknown")

    def test_network_query_sends_only_status_commands_and_closes(self):
        stream = Mock()
        stream.recv.side_effect = [b"\x12", b"\x72"]
        context = Mock()
        context.__enter__ = Mock(return_value=stream)
        context.__exit__ = Mock(return_value=False)
        with (
            TemporaryDirectory() as folder,
            patch.dict(os.environ, {"RECEIPT_PRINTER_CONNECTION": "network"}),
            patch.object(
                printer_status.socket, "create_connection", return_value=context
            ),
        ):
            result = printer_status.sensors(folder)
        self.assertEqual(result["paper"], "out")
        self.assertEqual(
            [call.args[0] for call in stream.sendall.call_args_list],
            [b"\x10\x04\x02", b"\x10\x04\x04"],
        )
        context.__exit__.assert_called_once()
        stream.settimeout.assert_called_with(1)

    def test_timeout_usb_busy_and_invalid_reply_remain_unknown(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(
                printer_status.socket, "create_connection", side_effect=TimeoutError()
            ) as connect,
        ):
            self.assertEqual(printer_status.sensors(folder)["paper"], "unknown")
            with patch.dict(os.environ, {"RECEIPT_PRINTER_CONNECTION": "usb"}):
                self.assertIn("USB", printer_status.sensors(folder)["message"])
            with file_lock(Path(folder) / "data" / "printer_diagnostic_run"):
                self.assertIn("deferred", printer_status.sensors(folder)["message"])
            (Path(folder) / "data" / ".print_now.lock").write_text(str(os.getpid()))
            connect.reset_mock()
            self.assertIn("deferred", printer_status.sensors(folder)["message"])
            connect.assert_not_called()


class PiAcceptanceTests(TestCase):
    def settings(self):
        return {"print_schedule": {"enabled": False, "time": "03:00"}}

    def test_offline_check_does_not_touch_service_or_printer(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(
                pi_acceptance,
                "service_status",
                side_effect=AssertionError("service call"),
            ),
            patch.object(
                pi_acceptance,
                "boot_fingerprint",
                side_effect=AssertionError("boot call"),
            ),
            patch(
                "receipt.printer.readiness", side_effect=AssertionError("printer call")
            ),
            patch(
                "receipt_settings.settings_state", return_value=(self.settings(), None)
            ),
            patch.object(
                pi_acceptance, "dependency_check", return_value=("passed", "pins match")
            ),
            patch("web_control.printer_setup.installation_checks", return_value=[]),
        ):
            report = pi_acceptance.check(root=folder, offline=True)
            self.assertEqual(report["result"], "passed")
            self.assertFalse(report["physical_complete"])
            self.assertFalse(list(Path(folder).rglob("*.json")))

    def test_reboot_and_reconnection_need_saved_evidence(self):
        with (
            TemporaryDirectory() as folder,
            patch(
                "receipt_settings.settings_state", return_value=(self.settings(), None)
            ),
            patch.object(
                pi_acceptance, "dependency_check", return_value=("passed", "pins match")
            ),
            patch("web_control.printer_setup.installation_checks", return_value=[]),
            patch.object(
                pi_acceptance,
                "service_status",
                return_value={"active": True, "enabled": True, "pid": 200},
            ),
            patch.object(pi_acceptance, "boot_fingerprint", return_value="newboot"),
            patch("receipt.printer.readiness", return_value=(True, "reachable")),
        ):
            report = pi_acceptance.check(root=folder, phase="after-reboot")
            self.assertEqual(
                next(
                    row["status"]
                    for row in report["checks"]
                    if row["name"] == "Reboot observed"
                ),
                "pending",
            )
            pi_acceptance.load_phases(folder).update(
                lambda value: value["phases"].update(
                    {
                        "baseline": {
                            "result": "passed",
                            "evidence": {"boot": "oldboot", "service": {"pid": 100}},
                        },
                        "disconnected": {
                            "result": "passed",
                            "evidence": {"printer_reachable": False},
                        },
                    }
                )
            )
            report = pi_acceptance.check(
                root=folder, phase="after-reboot", probe_printer=True
            )
            self.assertEqual(
                next(
                    row["status"]
                    for row in report["checks"]
                    if row["name"] == "Reboot observed"
                ),
                "passed",
            )
            report = pi_acceptance.check(
                root=folder, phase="reconnected", probe_printer=True
            )
            self.assertEqual(
                next(
                    row["status"]
                    for row in report["checks"]
                    if row["name"] == "Printer reconnection observed"
                ),
                "passed",
            )
            report = pi_acceptance.check(root=folder, phase="after-recovery")
            self.assertEqual(
                next(
                    row["status"]
                    for row in report["checks"]
                    if row["name"] == "Service process restarted"
                ),
                "passed",
            )

    def test_physical_confirmation_needs_new_scheduled_outcome(self):
        with (
            TemporaryDirectory() as folder,
            patch(
                "receipt_settings.settings_state", return_value=(self.settings(), None)
            ),
            patch.object(
                pi_acceptance, "dependency_check", return_value=("passed", "pins match")
            ),
            patch("web_control.printer_setup.installation_checks", return_value=[]),
            patch.object(pi_acceptance, "service_status", return_value={}),
        ):
            pi_acceptance.load_phases(folder).update(
                lambda value: value["phases"].update(
                    {
                        "baseline": {
                            "evidence": {"checked_at": "2026-01-01T00:00:00+00:00"}
                        }
                    }
                )
            )
            report = pi_acceptance.check(
                root=folder, phase="scheduled", confirm_paper=True
            )
            self.assertFalse(report["physical_complete"])
            self.assertEqual(
                next(
                    row["status"]
                    for row in report["checks"]
                    if row["name"] == "Paper collected"
                ),
                "pending",
            )
