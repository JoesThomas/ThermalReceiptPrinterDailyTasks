import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from receipt import archive, freshness
from receipt.capture import RecordingPrinter, load_capture
from receipt.live_preview import VirtualPrinter
from web_control import private_backup as backup

class PrivateReceiptTests(unittest.TestCase):
    def test_single_page_archive_does_not_copy_old_pages(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(archive, 'DIRECTORY', Path(directory)/'archive'):
            target = Path(directory)/'receipt.json'
            target.write_text(json.dumps({'pages': {'food': 'OLD FOOD'}, 'page_times': {'food': '2020-01-01'}, 'page_images': {}}))
            freshness.reset()
            freshness.mark('Weather')
            recorder = RecordingPrinter(VirtualPrinter())
            recorder.text('CURRENT WEATHER\n')
            recorder.cut()
            recorder.save('information', path=target)
            item = archive.load(archive.entries()[0]['id'])
            self.assertEqual(item['pages'], {'information': 'CURRENT WEATHER'})
            self.assertEqual(load_capture(target)['pages']['food'], 'OLD FOOD')
            self.assertEqual(item['freshness']['Weather']['status'], 'checked')
            with self.assertRaises(ValueError): archive.load('../outside')
            self.assertEqual(archive.entries('2000-01-01'), [])

    def test_reprint_uses_saved_page_without_collectors(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory, patch.object(archive, 'DIRECTORY', Path(directory)):
            identifier=archive.save({'information':'Saved text'}, {}, '2026-10-02T12:00:00+00:00', 'preview', {})
            printer=Mock()
            with patch('receipt.printer.open_printer',return_value=printer):
                archive.reprint(identifier,'information')
            printer.text.assert_any_call('Saved text')
            printer.cut.assert_called_once()
            printer.close.assert_called_once()

    def test_backup_round_trip_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'data').mkdir()
            (root/'data'/'to_buy.json').write_text('{"items":["Example item"]}')
            (root/'data'/'bank_tokens.json').write_text('{"secret":"excluded"}')
            raw=backup.export(root)
            self.assertNotIn(b'excluded', raw)
            value=backup.validate(raw)
            (root/'data'/'to_buy.json').write_text('{"items":[]}')
            backup.restore(root,value)
            self.assertEqual(json.loads((root/'data'/'to_buy.json').read_text())['items'],['Example item'])
            self.assertEqual(len(list((root/'data'/'private_backups').glob('*.json'))),1)
            for files in ({'../outside.json':{}},{'credentials.json':{}},{'future_tasks.json':{}},{'subscriptions.json':{'monthly':{}}}):
                with self.assertRaises(ValueError): backup.validate(json.dumps({'version':1,'files':files}).encode())
            with self.assertRaises(ValueError): backup.validate(b'x'*(backup.MAX_BYTES+1))

    def test_restore_failure_rolls_back_all_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'data').mkdir()
            target=root/'data'/'to_buy.json'; target.write_text('{"items":["Before"]}')
            original=backup.private_write
            def fail(path,raw):
                if path.name=='routines.json': raise OSError('simulated write failure')
                return original(path,raw)
            with patch.object(backup,'private_write',side_effect=fail):
                with self.assertRaises(OSError):
                    backup.restore(root, {'version':1,'files':{'to_buy.json':{'items':['After']},'routines.json':[]}})
            self.assertEqual(json.loads(target.read_text())['items'],['Before'])
            self.assertFalse((root/'data'/'routines.json').exists())
