import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_control import print_job


class PrintJobTests(unittest.TestCase):
    def test_records_failure_and_removes_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'job.lock'
            status = Path(tmp) / 'status.json'
            lock.write_text('123')
            with patch.object(print_job, 'LOCK', lock), patch.object(print_job, 'STATUS', status), \
                    patch.object(print_job, 'run_bounded') as run, \
                    patch.object(print_job.sys, 'argv', ['print_job.py', '--only', 'finance']):
                run.return_value = 1
                self.assertEqual(print_job.main(), 1)
            self.assertFalse(lock.exists())
            self.assertEqual(json.loads(status.read_text())['state'], 'failed')
            self.assertEqual(json.loads(status.read_text())['page'], 'finance')


if __name__ == '__main__':
    unittest.main()
