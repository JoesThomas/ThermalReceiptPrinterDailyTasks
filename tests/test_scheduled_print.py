import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web_control.scheduled_print import UK, next_print_time, print_once


class ScheduledPrintTests(unittest.TestCase):
    def test_next_run_uses_uk_three_am_and_never_catches_up_on_startup(self):
        before = datetime(2026, 9, 29, 1, 59, tzinfo=timezone.utc)
        self.assertEqual(next_print_time(before).isoformat(), '2026-09-29T03:00:00+01:00')
        after = datetime(2026, 9, 29, 3, 1, tzinfo=UK)
        self.assertEqual(next_print_time(after).isoformat(), '2026-09-30T03:00:00+01:00')

    def test_dst_switches_keep_local_three_am(self):
        self.assertEqual(next_print_time(datetime(2026, 3, 29, 0, tzinfo=timezone.utc)).isoformat(),
                         '2026-03-29T03:00:00+01:00')
        self.assertEqual(next_print_time(datetime(2026, 10, 25, 0, tzinfo=timezone.utc)).isoformat(),
                         '2026-10-25T03:00:00+00:00')

    def test_custom_time_disabled_and_dst_gap(self):
        settings = {'print_schedule': {'enabled': True, 'time': '08:45'}}
        now = datetime(2026, 10, 3, 7, 0, tzinfo=UK)
        self.assertEqual(next_print_time(now, settings).strftime('%H:%M'), '08:45')
        settings['print_schedule']['enabled'] = False
        self.assertIsNone(next_print_time(now, settings))
        settings['print_schedule'] = {'enabled': True, 'time': '01:30'}
        spring = next_print_time(datetime(2026, 3, 29, 0, tzinfo=UK), settings)
        self.assertEqual(spring.isoformat(), '2026-03-29T02:00:00+01:00')
        fall = next_print_time(datetime(2026, 10, 25, 0, tzinfo=UK), settings)
        self.assertEqual(fall.isoformat(), '2026-10-25T01:30:00+01:00')

    def test_running_scheduler_reloads_disabled_setting(self):
        from unittest.mock import patch
        from web_control.scheduled_print import schedule_loop
        stop = type('Stop', (), {})()
        stop.calls = 0
        stop.is_set = lambda: stop.calls >= 2
        def wait(seconds): stop.calls += 1
        stop.wait = wait
        configs = iter([(True, 3, 0), (False, 3, 0)])
        with patch('web_control.scheduled_print.schedule_options', side_effect=lambda: next(configs)), patch('web_control.scheduled_print.next_print_time', return_value=None) as next_run:
            schedule_loop(lambda args: self.fail('disabled print started'), stop)
            self.assertEqual(next_run.call_count, 2)

    def test_one_launch_per_day_and_busy_print_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'last'
            calls = []
            def start(args):
                calls.append(args)
                return (len(calls) > 1, 'Printer busy')
            today = datetime(2026, 9, 29).date()
            self.assertFalse(print_once(today, start, marker))
            self.assertFalse(marker.exists())
            self.assertTrue(print_once(today, start, marker))
            self.assertTrue(print_once(today, start, marker))
            self.assertEqual(calls, [[], []])
            self.assertEqual(marker.read_text().strip(), '2026-09-29')
            self.assertTrue(print_once(today.replace(day=30), start, marker))
            self.assertEqual(calls, [[], [], []])


if __name__ == '__main__':
    unittest.main()
