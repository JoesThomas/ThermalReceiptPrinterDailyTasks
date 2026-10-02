import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from web_control.job_runtime import run_bounded, JobCancelled
from web_control import print_job, preview_job


class JobFailsafeTests(unittest.TestCase):
    def test_real_hung_child_is_stopped_on_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, '-c', 'import time;time.sleep(60)'],
                        cwd=Path.cwd(), env=os.environ.copy(), timeout=.05)

    def test_timeout_and_cancellation_release_locks_and_preserve_status(self):
        for worker in (print_job, preview_job):
            for error, state in [(subprocess.TimeoutExpired('test', 600), 'timed_out'),
                                 (JobCancelled(), 'cancelled')]:
                with self.subTest(worker=worker.__name__, state=state), tempfile.TemporaryDirectory() as folder:
                    lock = Path(folder) / 'job.lock'
                    status = Path(folder) / 'status.json'
                    lock.write_text('123')
                    with patch.object(worker, 'LOCK', lock), patch.object(worker, 'STATUS', status), \
                         patch.object(worker, 'run_bounded', side_effect=error), \
                         patch.object(sys, 'argv', ['worker']):
                        self.assertIn(worker.main(), (124, 130))
                    saved = json.loads(status.read_text())
                    self.assertEqual(saved['state'], state)
                    self.assertTrue(saved['started_at'])
                    self.assertTrue(saved['job_id'])
                    self.assertFalse(lock.exists())

    def test_successful_child_returns_exit_code(self):
        self.assertEqual(run_bounded([sys.executable, '-c', 'pass'], cwd=Path.cwd(),
                                    env=os.environ.copy(), timeout=2), 0)

    def test_real_cancellation_stops_supervised_child(self):
        code = '''
import os,signal,threading,time
from pathlib import Path
from web_control.job_runtime import run_bounded, JobCancelled
threading.Timer(.2,lambda:os.kill(os.getpid(),signal.SIGTERM)).start()
try:
 run_bounded([__import__('sys').executable,'-c','import time;time.sleep(60)'],cwd=Path.cwd(),env=os.environ.copy(),timeout=5)
except JobCancelled:
 print('cancelled safely')
else:
 raise AssertionError('cancellation did not fire')
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                env=os.environ.copy(), timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('cancelled safely', result.stdout)

    def test_cancel_verifies_worker_before_signalling(self):
        try:
            from flask import Flask
        except ImportError:
            self.skipTest('Flask required')
        from web_control import job_controls
        from types import SimpleNamespace
        app = Flask(__name__)
        app.secret_key = 'test'
        app.add_url_rule('/', endpoint='index', view_func=lambda: 'home')
        app.add_url_rule('/preview', endpoint='preview', view_func=lambda: 'preview')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            (root / 'data' / '.print_now.lock').write_text('123')
            job_controls.register(app, lambda fn: fn, root, lambda: None, lambda: None)
            with app.test_client() as client, patch.object(job_controls.subprocess, 'run') as ps, \
                 patch.object(job_controls.os, 'getpgid', return_value=123), \
                 patch.object(job_controls.os, 'killpg') as stop:
                ps.return_value = SimpleNamespace(stdout='unrelated process')
                self.assertEqual(client.post('/jobs/cancel', data={'kind':'print'}).status_code, 302)
                stop.assert_not_called()
                ps.return_value.stdout = 'python ' + str(root / 'web_control' / 'print_job.py')
                client.post('/jobs/cancel', data={'kind':'print'})
                stop.assert_called_once()
                self.assertTrue((root / 'data' / '.print_now.lock').exists())
