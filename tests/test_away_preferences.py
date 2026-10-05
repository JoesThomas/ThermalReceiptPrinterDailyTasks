import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from receipt import lifestyle, repeat_guard
from meals import legacy_planner as meals
from finance.credit_limits import summary
from web_control import payment_explanations, print_job
from web_control.undo import restore


class AwayPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.patches = [patch.object(lifestyle, 'FILE', self.root/'data'/'lifestyle.json'), patch.object(payment_explanations, 'FILE', self.root/'data'/'finance_explanations.json')]
        for item in self.patches: item.start()
    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.folder.cleanup()
    def settings(self, travel=None):
        value=copy.deepcopy(lifestyle.DEFAULT)
        value['away'].update(enabled=True,departure='2026-10-05',**{'return':'2026-10-07'},travel_meals=travel or [])
        lifestyle.store().update(lambda current: current.update(value))
        return value

    def test_away_boundaries_travel_dates_and_auto_return(self):
        value=self.settings(['2026-10-06'])
        self.assertFalse(lifestyle.active(date(2026,10,4),value))
        self.assertTrue(lifestyle.skip_meal(date(2026,10,5),value))
        self.assertFalse(lifestyle.skip_meal(date(2026,10,6),value))
        self.assertFalse(lifestyle.active(date(2026,10,7),value))
        value['away']['return']='2026-10-05'
        with self.assertRaises(ValueError): lifestyle.validate(value)

    def test_recipe_overlay_keeps_original_and_shared_ingredients(self):
        value=self.settings()
        plan={'meals':[{'date':'2026-10-05','kind':'recipe','recipe':{'name':'Away meal','ingredients':['rice','chicken']}}, {'date':'2026-10-07','kind':'recipe','recipe':{'name':'Home meal','ingredients':['rice','fish']}}]}
        before=copy.deepcopy(plan)
        with patch.object(meals,'_pantry_has',return_value=False), patch.object(meals,'_override_for',return_value=None), patch.object(meals,'build_sunday_prep',return_value=[]):
            adjusted=lifestyle.apply_plan(plan, meals, value)
        self.assertEqual(plan,before)
        items=[item for group in adjusted['shopping'].values() for item in group]
        self.assertEqual(set(items),{'rice','fish'})
        self.assertEqual(adjusted['away_excluded_ingredients'],['chicken'])
        self.assertEqual(adjusted['meals'][0]['kind'],'away')
        self.assertEqual(adjusted['meals'][1]['kind'],'recipe')

    def test_cached_plan_is_adjusted_without_rewriting_original(self):
        self.settings()
        with patch.object(meals,'PLANS_DIR',self.root/'plans'), patch.object(meals,'build_sunday_prep',return_value=[]), patch.object(meals,'_pantry_has',return_value=False):
            path=meals.plan_path(date(2026,10,4)); meals._save(path, {'meals':[{'date':'2026-10-05','kind':'recipe','recipe':{'name':'Kept recipe','ingredients':['rice']}}]})
            original=path.read_bytes()
            self.assertEqual(meals.load_plan_for(date(2026,10,5))['meals'][0]['kind'],'away')
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(meals.load_plan_for(date(2026,10,5),raw=True)['meals'][0]['kind'],'recipe')
        with patch.object(meals,'recipes',side_effect=AssertionError('Recipe library should not be needed')):
            self.assertEqual(meals.get_meal(date(2026,10,5))['kind'],'away')

    def test_scheduled_away_job_saves_without_printer_readiness(self):
        lock=self.root/'lock';status=self.root/'status.json';lock.write_text(str(os.getpid()))
        with patch.object(print_job,'LOCK',lock), patch.object(print_job,'STATUS',status), patch.object(print_job,'ROOT',self.root), patch.object(print_job,'run_bounded',return_value=0) as run, patch.object(lifestyle,'active',return_value=True), patch('receipt.printer.readiness') as printer, patch.object(print_job.sys,'argv',['worker','--scheduled']):
            self.assertEqual(print_job.main(),0)
            self.assertIn('--live-preview',run.call_args.args[0])
            printer.assert_not_called()
        value=json.loads(status.read_text());self.assertTrue(value['preview_saved']);self.assertIn('Away mode',value['stage']);self.assertFalse(lock.exists())

    def test_repeat_guard_has_time_window_and_request_scope(self):
        repeat_guard.record(self.root,['--only','actions'])
        self.assertTrue(repeat_guard.recent(self.root,['--only','actions']))
        self.assertFalse(repeat_guard.recent(self.root,['--only','finance']))
        self.assertFalse(repeat_guard.recent(self.root,['--only','actions'],datetime.now(timezone.utc)+timedelta(minutes=4)))

    def test_credit_limits_do_not_change_projection_cash(self):
        cards=[{'name':'Example card','limit':'1000','used':'300','provider':'OTHER'}]
        row=summary(cards)[0]
        self.assertEqual(row['available'],700)
        self.assertEqual(row['percent'],30)
        row=summary([{**cards[0],'provider':'AMEX'}],{'AMEX':{'current':500}})[0]
        self.assertEqual(row['used'],500)
        self.assertEqual(row['available'],500)
        self.assertEqual(summary([{**cards[0],'used':None}])[0]['available'],None)
        self.assertEqual(summary([{**cards[0],'used':'1500'}])[0]['over'],500)

    def test_finance_explanations_and_price_change_need_separate_months(self):
        from finance_trends import load_rules
        transactions=[{'date':'2026-09-01','amount':-10,'description':'EXAMPLE SERVICE'}, {'date':'2026-10-01','amount':-15,'description':'EXAMPLE SERVICE'}]
        rows=[{'item':{'name':'Example','amount':10,'match':['EXAMPLE SERVICE']},'transaction':None}]
        payment_explanations.capture(transactions,rows,date(2026,10,5),{'EXAMPLE SERVICE':'SUBSCRIPTION'}, {'EXAMPLE SERVICE':'SUBSCRIPTION'})
        value=payment_explanations.store().read()
        self.assertEqual(value['payments'][0]['basis'],'Manual merchant rule')
        self.assertEqual(value['price_changes'][0]['previous'],10)
        self.assertEqual(value['price_changes'][0]['current'],15)
        self.assertFalse(value['commitments'][0]['paid'])
        payment_explanations.correction({'date':'2026-10-01','merchant':'Example','amount':15},'SPORTS','purchase')
        payment_explanations.capture([],[],date(2026,10,5),{}, {})
        self.assertEqual(len(payment_explanations.store().read()['audit']),1)

    def test_undo_will_not_overwrite_a_later_delivery_edit(self):
        from actions import delivery_state
        path=self.root/'deliveries.json'
        path.write_text(json.dumps({'items':{'example':{'confirmed':True}}}))
        with patch.object(delivery_state,'FILE',path):
            restore({'kind':'delivery','id':'example','before':False,'after':True})
            self.assertFalse(delivery_state.load_state()['items']['example']['confirmed'])
            with self.assertRaises(ValueError): restore({'kind':'delivery','id':'example','before':False,'after':True})

    def test_retention_defaults_keep_everything_and_preserve_ledgers(self):
        from storage import write_json
        directory=self.root/'data'/'receipt_archive';directory.mkdir(parents=True)
        old=directory/'old.json';write_json(old,{'captured_at':'2026-01-01T12:00:00+00:00'})
        ledger=self.root/'data'/'premium_bonds.json';write_json(ledger,{'prizes':[]})
        self.assertEqual(lifestyle.prune(self.root,date(2026,10,5))['receipts'],0)
        lifestyle.store().update(lambda value:value['retention'].update(receipts=30))
        self.assertEqual(lifestyle.prune(self.root,date(2026,10,5))['receipts'],1)
        self.assertTrue(ledger.exists())

    def test_new_private_state_is_validated_for_backup(self):
        from web_control.private_backup import validate
        value={'version':1,'files':{'lifestyle.json':copy.deepcopy(lifestyle.DEFAULT)}}
        self.assertIn('lifestyle.json',validate(json.dumps(value).encode())['files'])
        value['files']['lifestyle.json']['away']['return']='not-a-date'
        with self.assertRaises(ValueError):validate(json.dumps(value).encode())
