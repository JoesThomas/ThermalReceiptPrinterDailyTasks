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
