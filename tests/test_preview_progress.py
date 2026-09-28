import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from receipt.local_time import uk_receipt_time
from receipt import preview_progress
from web_control import preview_job


class PreviewProgressTests(unittest.TestCase):
    def test_receipt_time_uses_uk_daylight_saving(self):
        self.assertEqual(uk_receipt_time("2026-09-28T20:15:00+00:00"),
                         "28 Sep 2026, 21:15 BST")
        self.assertEqual(uk_receipt_time("2026-12-28T20:15:00Z"),
                         "28 Dec 2026, 20:15 GMT")
        self.assertEqual(uk_receipt_time("invalid"), "")

    def test_worker_progress_keeps_start_time_and_reports_saving(self):
        with TemporaryDirectory() as directory:
            status_file = Path(directory) / "status.json"
            with patch.object(preview_job, "STATUS", status_file), \
                 patch.object(preview_progress, "STATUS", status_file), \
                 patch.dict(os.environ, {"RECEIPT_LIVE_PREVIEW": "1"}):
                preview_job.save_status("running")
                started_at = json.loads(status_file.read_text())["started_at"]
                preview_progress.report("Fetching calendar events", 1, 5)
                running = json.loads(status_file.read_text())
                self.assertEqual((running["stage"], running["completed"], running["total"]),
                                 ("Fetching calendar events", 1, 5))
                self.assertEqual(running["started_at"], started_at)
                preview_progress.report("Saving generated preview", 4, 5)
                preview_job.save_status("completed")
                completed = json.loads(status_file.read_text())
                self.assertEqual(completed["started_at"], started_at)
                self.assertEqual(completed["completed"], 4)


if __name__ == "__main__":
    unittest.main()
