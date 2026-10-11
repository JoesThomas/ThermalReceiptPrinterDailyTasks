import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch
from storage import write_json
from finance import cache, wealth_history
from finance.yearly_subscriptions import annual_subscription_rows
from receipt.capture import load_capture
from receipt import archive
from services import subscriptions
from services.safe_xml import parse_feed, MAX_FEED_BYTES
from validation import validate_recipe, validate_project
from defusedxml.common import DTDForbidden
ROOT=Path(__file__).resolve().parents[1]

class CodebaseReliabilityTests(unittest.TestCase):
    def test_future_tasks_request_survives_settings_reload(self):
        import receipt_settings as settings
        with tempfile.TemporaryDirectory() as folder,patch.object(settings,'SETTINGS_FILE',Path(folder)/'settings.json'):
            value=settings.load_receipt_settings()
            value['one_shot']['future_tasks']=True
            settings.save_receipt_settings(value)
            self.assertTrue(settings.one_shot_requested(settings.load_receipt_settings(),'future_tasks'))

    def test_regular_payment_type_is_parsed_before_use(self):
        node=next(n for n in ast.parse((ROOT/'services/live_pipeline.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='load_regular_payments')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'<regular-payments>','exec'),namespace)
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'payments.txt';file.write_text('Example bill | 20 | 3 | example | bill\nExample other | 30 | 4\n')
            self.assertEqual([r['type'] for r in namespace['load_regular_payments'](file)],['bill','other'])

    def test_refund_does_not_overwrite_monthly_payment(self):
        data={'monthly':[{'name':'Example','amount':20,'match':['service']}],'yearly':[],'instalments':[]}
        rows=[{'date':'2026-10-01','amount':-20,'description':'service'},
              {'date':'2026-10-02','amount':50,'transaction_type':'CREDIT','description':'service refund'},
              {'date':'2026-10-02','amount':float('nan'),'description':'service'}]
        with patch.object(subscriptions,'load_subscriptions',return_value=data),patch.object(subscriptions,'save_subscriptions'):
            self.assertEqual(subscriptions.update_subscriptions_from_transactions(rows),[])
        self.assertEqual(data['monthly'][0]['amount'],20)
        self.assertEqual(data['monthly'][0]['last_paid'],'2026-10-01')
        self.assertEqual(subscriptions._date({'timestamp':'2026-09-30T23:30:00Z'}),'2026-10-01')

    def test_annual_payment_dates_use_uk_time_and_nan_is_not_a_match(self):
        bill={'name':'Example','amount':120,'renewal_date':'2026-10-01','match':['service']}
        rows=[{'timestamp':'2026-09-30T23:30:00Z','amount':-120,'description':'service'}]
        self.assertEqual(annual_subscription_rows([bill],rows,date(2026,10,1))[0]['bank_paid_date'],date(2026,10,1))
        rows[0]['amount']=float('nan')
        self.assertIsNone(annual_subscription_rows([bill],rows,date(2026,10,1))[0]['bank_paid_date'])

    def test_atomic_private_writes_do_not_share_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'private.json'
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda n:write_json(target,{'value':n}),range(30)))
            self.assertIn(json.loads(target.read_text())['value'],range(30))
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])
            with self.assertRaises(ValueError):write_json(target,{'value':float('nan')})
            self.assertIn(json.loads(target.read_text())['value'],range(30))

    def test_bad_saved_receipts_and_cache_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'receipt.json';file.write_text('[]')
            self.assertIsNone(load_capture(file))
            file.write_text('{"pages":{"finance":"saved"},"page_images":[],"freshness":{"Bank":null}}')
            self.assertEqual(load_capture(file)['freshness'],{})
            identifier='20261002T000000Z-'+'a'*12
            (Path(folder)/(identifier+'.json')).write_text('{}')
            with patch.object(archive,'DIRECTORY',Path(folder)),self.assertRaises(ValueError):archive.load(identifier)
        for name in ('../outside','x/y',''):
            with self.assertRaises(ValueError):cache.put(name,1)

    def test_rss_rejects_dtd_entities_and_large_feeds(self):
        self.assertEqual(parse_feed(b'<rss><channel/></rss>').tag,'rss')
        with self.assertRaises(DTDForbidden):parse_feed(b'<!DOCTYPE rss [<!ENTITY item "expanded">]><rss>&item;</rss>')
        with self.assertRaises(ValueError):parse_feed(b'x'*(MAX_FEED_BYTES+1))

    def test_undated_investments_do_not_gain_a_fresh_valuation_date(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(wealth_history,'HISTORY_FILE',Path(folder)/'history.json'):
            wealth_history.capture_local({'accounts':[]},{'updated':None,'accounts':[{'name':'Example ISA','value':100}]},date(2026,10,2))
            self.assertEqual(wealth_history.load_history(),[])

    def test_optional_private_runtime_files_do_not_fail_initial_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(validate_project({'savings':root/'savings.json','pantry':root/'pantry.json'}),[])
            self.assertTrue(validate_project({'recipes':root/'recipes.json'}))

    def test_recipe_validation_and_offline_preview_need_no_live_dependencies(self):
        self.assertTrue(validate_recipe({'name':'Example','ingredients':[],'method':None},0))
        with tempfile.TemporaryDirectory() as folder:
            code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import main;main.BASE_DIR=Path(sys.argv[2]);sys.argv=['main.py','--preview'];main.main()"
            result=subprocess.run([sys.executable,'-S','-c',code,str(ROOT),folder],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((Path(folder)/'receipt_preview.txt').exists())
