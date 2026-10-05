import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from web_control import maintenance, print_job, private_backup
from web_control.setup_tools import reminders, checklist
from receipt import archive, printer

UK = ZoneInfo('Europe/London')


class MaintenanceTests(unittest.TestCase):
    def test_daily_snapshot_retention_private_permissions_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'data').mkdir()
            source = root / 'data' / 'to_buy.json'
            source.write_text('{"items":["Example"]}')
            (root / 'passwords.json').write_text('{"secret":"NEVER EXPORT"}')
            directory = root / 'data' / 'private_backups'; directory.mkdir()
            rollback = directory / 'rollback.json'; rollback.write_text('{}')
            settings = {'private_backup': {'enabled': True, 'keep': 7}}
            first = datetime(2026, 10, 1, 23, 30, tzinfo=UK)
            for day in range(9):
                now = first + timedelta(days=day)
                self.assertTrue(maintenance.create(root, settings=settings, now=now))
                self.assertFalse(maintenance.create(root, settings=settings, now=now))
            rows = maintenance.saved(root)
            self.assertEqual(len(rows), 7)
            self.assertTrue(rollback.exists())
            raw = maintenance.read_saved(root, rows[0]['name'])
            self.assertNotIn(b'NEVER EXPORT', raw)
            self.assertEqual((directory / rows[0]['name']).stat().st_mode & 0o777, 0o600)
            source.write_text('{"items":[]}')
            private_backup.restore(root, private_backup.validate(raw))
            self.assertEqual(json.loads(source.read_text())['items'], ['Example'])
            with self.assertRaises(ValueError): maintenance.read_saved(root, '../passwords.json')
            self.assertFalse(maintenance.create(root, settings={'private_backup': {'enabled': False, 'keep': 7}}, now=first))

    def test_backup_busy_or_invalid_data_does_not_prune(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'data').mkdir()
            (root / 'data' / 'to_buy.json').write_text('{"items":[]}')
            lock = root / 'data' / '.print_now.lock'; lock.write_text(str(os.getpid()))
            self.assertFalse(maintenance.create(root, force=True))
            lock.unlink()
            (root / 'data' / 'to_buy.json').write_text('bad json')
            with self.assertRaises(ValueError): maintenance.create(root, force=True)
            self.assertEqual(maintenance.saved(root), [])

    def test_reminders_boundaries_and_end_date_prevents_later_renewal(self):
        today = date(2026, 10, 4)
        data = {'monthly': [{'name': 'Broadband', 'end_date': '2026-12-03'},
                            {'name': 'Later', 'end_date': '2026-12-04'},
                            {'name': 'Expired', 'end_date': '2026-10-03'}],
                'yearly': [{'name': 'Renewing', 'renewal_date': '2020-10-10'},
                           {'name': 'Ended', 'renewal_date': '2020-10-10', 'end_date': '2026-10-03'},
                           {'name': 'No date'}]}
        rows = reminders(data, today)
        self.assertEqual([x['name'] for x in rows], ['Renewing', 'Broadband'])
        self.assertEqual(rows[1]['days'], 60)

    def test_archive_search_text_case_insensitive_combines_date(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(archive, 'DIRECTORY', Path(folder)):
            archive.save({'actions': 'Learn piano', 'finance': 'Coffee £12'}, {},
                         '2026-10-03T23:30:00+00:00', 'preview', {})
            self.assertEqual(len(archive.entries('2026-10-04', 'PIANO')), 1)
            self.assertEqual(len(archive.entries(query='coffee')), 1)
            self.assertEqual(archive.entries('2026-10-03', 'piano'), [])
            self.assertEqual(archive.entries(query='unmatched'), [])

    def test_readiness_sends_no_printer_commands_and_bounds_timeout(self):
        with patch.dict(os.environ, {}, clear=True), patch('socket.create_connection') as connect:
            self.assertTrue(printer.readiness()[0])
            connect.assert_called_once_with((printer.DEFAULT_NETWORK_HOST, 9100), timeout=3)
            connect.side_effect = TimeoutError()
            self.assertFalse(printer.readiness()[0])
        with patch.dict(os.environ, {'RECEIPT_PRINTER_CONNECTION': 'usb'}, clear=True), patch('socket.create_connection') as connect:
            self.assertIsNone(printer.readiness()[0]); connect.assert_not_called()

    def test_scheduled_offline_saves_preview_and_releases_job_lock(self):
        import sys
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); lock = root / 'lock'; status = root / 'status.json'
            lock.write_text(str(os.getpid()))
            with patch.object(print_job, 'ROOT', root), patch.object(print_job, 'LOCK', lock), \
                 patch.object(print_job, 'STATUS', status), patch.object(sys, 'argv', ['worker', '--scheduled']), \
                 patch('receipt.printer.readiness', return_value=(False, 'Offline')), \
                 patch.object(print_job, 'run_bounded', return_value=0) as run:
                self.assertEqual(print_job.main(), 1)
                self.assertIn('--live-preview', run.call_args.args[0])
                self.assertNotIn('--scheduled', run.call_args.args[0])
                self.assertEqual(run.call_count, 1)
            value = json.loads(status.read_text())
            self.assertEqual(value['state'], 'failed')
            self.assertTrue(value['preview_saved'])
            self.assertIn('live preview saved', value['stage'])
            self.assertFalse(lock.exists())

    def test_checklist_is_local_and_handles_missing_or_invalid_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'data').mkdir()
            (root / 'data' / 'daily_lists.json').write_text('{"items":null}')
            rows = checklist(root)
            self.assertFalse(next(row for row in rows if row['name'] == 'Bin collections')['configured'])

    def test_fallback_progress_updates_print_job_instead_of_preview_job(self):
        from receipt import preview_progress
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            target = directory / 'live_preview_status.json'
            with patch.object(preview_progress, 'STATUS', target), \
                 patch.dict(os.environ, {'RECEIPT_LIVE_PREVIEW': '1', 'RECEIPT_FALLBACK_PREVIEW': '1'}, clear=True):
                preview_progress.report('Fetching calendar', 1, 5)
            self.assertFalse(target.exists())
            self.assertEqual(json.loads((directory / 'web_print_status.json').read_text())['stage'], 'Fetching calendar')
