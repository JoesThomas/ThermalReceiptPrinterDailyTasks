import unittest
from copy import deepcopy
from datetime import date
from decimal import Decimal
from finance import assets, cash_scenarios, rental_tax


class PropertyScenarioTests(unittest.TestCase):
    def state(self):
        return {'schema_version':1,'mortgages':[{'id':'111111111111','name':'Home loan','balance':'60000','date':'2026-10-01'}],
                'properties':[{'id':'222222222222','name':'Rental property','address':'Private address','url':'','share':'50','mortgage':'111111111111',
                               'valuations':[{'value':'200000','low':'180000','high':'220000','date':'2026-10-01','source':'Manual'}]}]}

    def test_ownership_and_debt_are_deducted_once(self):
        state=self.state();debts=assets.merged_debts([{'name':'HOME LOAN','type':'mortgage','balance':'70000','monthly_commitment_name':'Mortgage payment'}],state)
        self.assertEqual(len(debts),1);self.assertEqual(debts[0]['balance'],'60000')
        self.assertEqual(debts[0]['monthly_commitment_name'],'Mortgage payment')
        view=assets.net_worth(5000,10000,20000,debts,{'physical_cash_held':500},date(2026,10,5),state)
        self.assertEqual(view['properties'][0]['equity'],40000)
        self.assertEqual(view['known_total'],75500)
        self.assertNotIn('Private address',view['components'])

    def test_missing_stale_and_negative_equity(self):
        state=self.state();state['properties'][0]['valuations'][0]['date']='2026-01-01'
        state['mortgages'][0]['balance']='120000'
        view=assets.property_review(state,date(2026,10,5))
        self.assertTrue(view['stale']);self.assertEqual(view['equity'],-20000)
        state['properties'][0]['valuations']=[]
        self.assertTrue(assets.property_review(state)['missing'])

    def test_invalid_link_range_and_unsafe_url(self):
        state=self.state();state['properties'][0]['url']='javascript:alert(1)'
        with self.assertRaises(ValueError):assets.validate(state)
        state=self.state();state['properties'][0]['valuations'][0]['low']='210000'
        with self.assertRaises(ValueError):assets.validate(state)
        state=self.state();state['properties'].append({**deepcopy(state['properties'][0]),'id':'333333333333'})
        with self.assertRaises(ValueError):assets.validate(state)
        with self.assertRaises(ValueError):assets.merged_debts([{'name':'Home loan','type':'credit_card'}],self.state())

    def test_scenario_isolated_income_vacancy_repair(self):
        today=date(2026,10,5)
        projection={'valid':True,'cash':Decimal(5000),'buffer':Decimal(1000),'events':[],'daily':Decimal(0)}
        config={'salary':'4500','rent':'800','vacancy':'1','repair':'500','start':'2026-10-31','months':'2'}
        original=deepcopy(projection)
        view=cash_scenarios.build(projection,config,today)
        self.assertEqual(view['base_end'],4000)
        self.assertEqual(view['end_cash'],13300)
        self.assertEqual(view['payments'][1]['date'],date(2026,11,30))
        self.assertEqual(view['payments'][0]['rent'],0)
        self.assertEqual(projection,original)
        projection['valid']=False
        self.assertFalse(cash_scenarios.build(projection,config,today)['valid'])

    def test_daily_minimum_catches_between_chart_points(self):
        today=date(2026,10,5)
        projection={'valid':True,'cash':Decimal(2000),'buffer':Decimal(1000),'events':[{'date':date(2026,10,6),'amount':Decimal(2000)}],'daily':Decimal(0)}
        config={'salary':'5000','rent':'0','vacancy':'0','repair':'0','start':'2026-10-10','months':'1'}
        result=cash_scenarios.build(projection,config,today)
        self.assertEqual(result['run_out'],date(2026,10,6))
        self.assertEqual(result['low'],-1000)

    def test_tax_rule_boundaries_and_versioned_breakdown(self):
        self.assertEqual(rental_tax.income_tax(Decimal(12570))[0],0)
        self.assertEqual(rental_tax.income_tax(Decimal(50270))[0],7540)
        self.assertEqual(rental_tax.income_tax(Decimal(125140))[0],42516)
        value={**rental_tax.DEFAULT,**{key:'0' for key in rental_tax.FIELDS},'enabled':True,'rent':'9600','other_income':'60000'}
        result=rental_tax.estimate(value,date(2026,10,5))
        self.assertEqual(result['combined_tax']-result['base_tax']-result['relief'],result['tax'])
        self.assertEqual(result['rules']['version'],'2026-27-ewni-v1')

    def test_receipt_uses_shared_totals_without_printing_addresses(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        import json
        from finance.receipt import print_integrated_finance
        lines=[]
        class Printer:
            def text(self,value): pass
            def set(self,**kwargs): pass
        with TemporaryDirectory() as folder:
            settings=Path(folder)/'settings.json'
            settings.write_text(json.dumps({'physical_cash_held':500,'runway_daily_spend':10,'commitments':[{'name':'Home loan','amount':100,'due_date':'2026-10-10'}]}))
            with patch.object(assets,'load',return_value=self.state()),patch('finance.receipt.load_savings',return_value={'accounts':[]}),patch('finance.receipt.load_investments',return_value={'accounts':[]}),patch('finance.wealth_history.capture_local'),patch('finance.wealth_history.review',return_value={'accounts':[],'savings':0,'investments':0,'month':'2026-10'}):
                print_integrated_finance(Printer(),lambda printer,text:lines.append(text),lambda printer,char='-':None,
                    {'HSBC':{'available':5000},'MONZO':{'available':1000},'AMEX':{'current':0}},transactions=[],finance_settings_file=settings,today=date(2026,10,5))
        self.assertIn('ASSETS & RECORDED NET WORTH [E]',lines)
        self.assertTrue(any('RECORDED NET WORTH' in row and '46,500.00' in row for row in lines))
        self.assertFalse(any('Private address' in row for row in lines))
