import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from web_control.job_process import wait_for_job


class JobProcessTests(unittest.TestCase):
    def test_reaps_worker_and_removes_owned_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "job.lock"
            lock.write_text("123")
            process = Mock(pid=123)
            wait_for_job(process, lock)
            process.wait.assert_called_once_with()
            self.assertFalse(lock.exists())

    def test_preserves_replacement_job_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "job.lock"
            lock.write_text("456")
            wait_for_job(Mock(pid=123), lock)
            self.assertEqual(lock.read_text(), "456")

    def test_missing_lock_still_reaps_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            process = Mock(pid=123)
            wait_for_job(process, Path(folder) / "job.lock")
            process.wait.assert_called_once_with()
