import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal
from datetime import date,datetime,timezone
from finance import bank_accounts
from receipt import archive,recovery
from services import calendar_locations
from web_control import maintenance,backup_health


class ReliabilityTests(unittest.TestCase):
    def test_multiple_selected_accounts_exclusions_and_private_metadata(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(bank_accounts,'SELECTION',Path(folder)/'selection.json'),patch.object(bank_accounts,'CATALOG',Path(folder)/'catalog.json'):
            def get(token,path):
                if path=='/accounts':return {'results':[{'account_id':token+'-a','display_name':'Main'},{'account_id':token+'-b','display_name':'Second'}]}
                if path=='/cards':return {'results':[{'account_id':'card'}]}
                return {'results':[{'current':100 if path.endswith('a/balance') else 200,'available':90 if path.endswith('a/balance') else 180,'currency':'GBP'}]}
            result=bank_accounts.collect(lambda provider,unused:provider,lambda provider:'PRIVATE-TOKEN',get)
            self.assertEqual(result['HSBC']['available'],90)
            bank_accounts.choose({'HSBC':['HSBC-a','HSBC-b'],'MONZO':[]})
            result=bank_accounts.collect(lambda provider,unused:provider,lambda provider:'PRIVATE-TOKEN',get)
            self.assertEqual(result['HSBC']['available'],270)
            self.assertEqual(result['MONZO']['available'],0)
            self.assertEqual(len(result['HSBC']['accounts']),2)
            self.assertNotIn('PRIVATE-TOKEN',bank_accounts.CATALOG.read_text())
            self.assertEqual(bank_accounts.SELECTION.stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError): bank_accounts.choose({'HSBC':['missing'],'MONZO':[]})
            with self.assertRaises(ValueError): bank_accounts.choose({'HSBC':[],'MONZO':[]})
            bank_accounts.SELECTION.write_text('{"HSBC":["missing"]}')
            with self.assertRaises(RuntimeError):bank_accounts.collect(lambda p,t:p,lambda p:'token',get)

    def test_location_override_applies_to_copy_and_reset(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(calendar_locations,'FILE',Path(folder)/'locations.json'):
            original={'uid':'event','date':date(2026,10,4),'time':'10:00','title':'Example','location':'Original'}
            key=calendar_locations.identity(original)
            calendar_locations.save(key,'Corrected')
            row=calendar_locations.apply([original])[0]
            self.assertEqual(row['location'],'Corrected');self.assertEqual(original['location'],'Original')
            calendar_locations.save(key,None)
            self.assertEqual(calendar_locations.apply([original])[0]['location'],'Original')

    def test_backup_restore_drill_does_not_touch_live_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            live=root/'data'/'to_buy.json';live.write_text('{"items":["Original"]}')
            maintenance.create(root,force=True)
            live.write_text('{"items":["Changed after backup"]}')
            result=backup_health.check(root,force=True)
            self.assertEqual(result['status'],'passed')
            self.assertIn('Changed after backup',live.read_text())
            latest=next((root/'data'/'private_backups').glob('auto-*.json'));latest.write_text('broken')
            self.assertEqual(backup_health.check(root,force=True)['status'],'failed')

    def test_collection_status_is_explicit_and_undoable(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(recovery,'FILE',Path(folder)/'recovery.json'):
            identifier='20261004T120000Z-aaaaaaaaaaaa'
            self.assertTrue(recovery.status(identifier,'preview').startswith('Generated'))
            recovery.mark(identifier,'sent_at')
            self.assertTrue(recovery.status(identifier,'preview').startswith('Sent'))
            recovery.mark(identifier,'collected_at')
            self.assertTrue(recovery.status(identifier,'preview').startswith('Collected'))
            recovery.mark(identifier,'collected_at',False)
            self.assertTrue(recovery.status(identifier,'preview').startswith('Sent'))

    def test_complete_generation_is_saved_before_printer_failure(self):
        import importlib.util,sys
        from types import ModuleType,SimpleNamespace
        from receipt.capture import RecordingPrinter
        from unittest.mock import Mock
        pipeline=SimpleNamespace(Usb=object())
        def run(**kwargs):
            recorder=pipeline.Usb()
            recorder.text('Generated before network failure\n');recorder.cut()
        pipeline.run_live_pipeline=run
        services=ModuleType('services');services.__path__=[];services.live_pipeline=pipeline
        target=Mock();target.open.side_effect=OSError('printer offline')
        with patch.dict(sys.modules,{'services':services,'services.live_pipeline':pipeline}),patch('receipt.printer.DeferredPhysicalPrinter',return_value=target),patch.object(RecordingPrinter,'save') as save:
            spec=importlib.util.spec_from_file_location('recovery_app_test',Path('app.py'))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with self.assertRaises(OSError):module.run_live(only_page='information')
            save.assert_called_once()
            self.assertTrue(save.call_args.kwargs['replace'])
            target.close.assert_called_once()
