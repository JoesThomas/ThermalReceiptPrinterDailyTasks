import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from finance import planning
from receipt.selection import validate as sections
from receipt.build import build
from receipt.layout import OrderedPrinter
from receipt.live_preview import VirtualPrinter
from receipt.capture import RecordingPrinter, load_capture
from types import SimpleNamespace


class FinancePlanningTests(unittest.TestCase):
    today=date(2026,10,4)

    def projection(self):
        return {'valid':True,'cash':Decimal(1000),'buffer':Decimal(100),'daily':Decimal(10),
                'events':[],'horizon':100,'horizon_end_date':self.today+timedelta(days=100)}

    def test_purchase_scenario_leaves_main_forecast_unchanged(self):
        projection=self.projection()
        purchase={'id':'a'*12,'name':'Optional purchase','amount':'200','date':self.today.isoformat(),'enabled':True}
        result=planning.scenario(projection,[purchase],self.today)
        self.assertEqual(result['days'],71)
        self.assertEqual(projection['cash'],Decimal(1000))
        purchase['enabled']=False
        self.assertEqual(planning.scenario(projection,[purchase],self.today)['days'],91)
        projection['valid']=False
        self.assertFalse(planning.scenario(projection,[purchase],self.today)['valid'])

    def test_savings_priorities_cap_space_and_allow_for_purchase(self):
        plan={'buckets':[{'name':'Savings contribution','amount':Decimal(500)}],'end':self.today+timedelta(days=20)}
        rows=[{'name':'Bonds','kind':'premium','priority':1,'amount':'300'},
              {'name':'ISA','kind':'isa','priority':2,'amount':'300'}]
        goals={'premium':{'remaining':Decimal(100)},'shared':{'remaining':Decimal(250)}}
        purchase={'enabled':True,'date':self.today.isoformat(),'amount':'100'}
        result=planning.allocation(plan,rows,goals,[purchase],self.today)
        self.assertEqual([r['allocated'] for r in result['rows']],[Decimal(100),Decimal(250)])
        self.assertEqual(result['unallocated'],Decimal(50))
        self.assertEqual(planning.allocation({},rows,goals,[],self.today)['available'],None)

    def test_shared_salary_target_uses_priorities_unless_manually_overridden(self):
        from finance.salary_plan import build as salary_plan
        priorities=[{'id':'a'*12,'name':'Savings','kind':'other','amount':'200','priority':1}]
        projection={'payday':self.today+timedelta(days=10),'events':[], 'daily':Decimal(10),
                    'valid':True,'cash':Decimal(1000),'buffer':Decimal(0)}
        with patch('finance.planning.load',return_value={'priorities':priorities}):
            args=([{'date':self.today.isoformat(),'amount':1000}],[],{'HSBC':{'available':1000}},projection)
            result=salary_plan(*args,{},None,self.today)
            self.assertEqual(result['target'],Decimal(200))
            result=salary_plan(*args,{'salary_savings_target':100},None,self.today)
            self.assertEqual(result['target'],Decimal(100))

    def test_private_plan_validation_and_storage(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(planning,'FILE',Path(folder)/'plan.json'):
            row={'id':'a'*12,'name':'Purchase','amount':'20','date':'2026-10-10','enabled':True}
            planning.update(lambda value:value.update(purchases=[row]))
            self.assertEqual(planning.load()['purchases'][0]['amount'],'20')
            self.assertEqual(planning.FILE.stat().st_mode&0o777,0o600)
            row['amount']='NaN'
            with self.assertRaises(ValueError):planning.update(lambda value:value.update(purchases=[row]))
            self.assertEqual(planning.load()['purchases'][0]['amount'],'20')

    def test_reminders_include_renewals_and_contract_endings(self):
        result=planning.reminders({},[{'name':'Broadband','end_date':'2026-11-01'}],
            [{'name':'Annual service','renewal_date':'2026-10-20'}],{},self.today)
        self.assertEqual([r['kind'] for r in result],['Annual renewal','Contract ending'])

    def test_selected_sections_keep_correct_page_names_in_capture(self):
        pipeline=SimpleNamespace(Usb=object())
        def run(**options):
            recorder=pipeline.Usb()
            ordered=OrderedPrinter(recorder,['food','actions','information','finance'])
            for name in ['information','actions','food','finance']:
                if name in options['selected_pages']:
                    ordered.begin(name);ordered.text(name+' text');ordered.cut()
            ordered.flush()
        with tempfile.TemporaryDirectory() as folder,patch('receipt.capture.LIVE_PREVIEW_FILE',Path(folder)/'preview.json'),patch('receipt.archive.DIRECTORY',Path(folder)/'archive'):
            recorder=build(pipeline,run,VirtualPrinter,selected_pages=['actions','finance'])
            value=load_capture(Path(folder)/'preview.json')
            self.assertEqual(set(value['pages']),{'actions','finance'})
            self.assertEqual(value['pages']['finance'],'finance text')
        for invalid in ([],['actions','actions'],['unknown']):
            with self.assertRaises(ValueError):sections(invalid)
