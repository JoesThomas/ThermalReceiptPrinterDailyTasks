import unittest
from datetime import date
from decimal import Decimal
from finance.salary_plan import reserves,build
from finance.projection import build_projection


class SalaryPlanTests(unittest.TestCase):
    def test_reserves_are_not_double_counted_and_cash_is_protected(self):
        settings={'emergency_buffer':500,'hsbc_emergency_reserve':500,'physical_cash_target':150,'physical_cash_held':50,'physical_cash_date':'2026-10-04'}
        self.assertEqual(reserves(settings)['buffer'],600)
        settings['physical_cash_held']=150
        self.assertEqual(reserves(settings)['buffer'],500)
        self.assertEqual(reserves(settings)['percent'],100)

    def test_salary_allocation_caps_cash_and_adds_up(self):
        today=date(2026,10,4)
        balances={'HSBC':{'available':2000},'MONZO':{'available':1500}}
        transactions=[{'date':'2026-10-02','amount':-400,'description':'Example store'}]
        settings={'hsbc_emergency_reserve':500,'physical_cash_target':150,'physical_cash_held':50,'runway_daily_spend':20,'next_payday':'2026-10-10','salary_savings_target':500,'commitments':[{'name':'Example bill','amount':700,'due_date':'2026-10-08'}]}
        projection=build_projection(balances,transactions,[],[],settings,today)
        salary=[{'date':date(2026,10,1),'amount':3000}]
        result=build(salary,transactions,balances,projection,settings,None,today)
        self.assertTrue(result['valid'])
        self.assertEqual(result['available'],2600)
        self.assertEqual(sum(b['amount'] for b in result['buckets']),2600)
        self.assertEqual(result['buckets'][0]['amount'],700)
        self.assertEqual(result['buckets'][1]['amount'],100)
        self.assertEqual(result['buckets'][2]['amount'],500)
        self.assertEqual(result['buckets'][3]['amount'],1300)
        self.assertEqual(projection['buffer'],600)

    def test_below_bank_reserve_and_partial_data_withhold_plan(self):
        today=date(2026,10,4);balances={'HSBC':{'available':400},'MONZO':{'available':500}}
        settings={'hsbc_emergency_reserve':500,'runway_daily_spend':10}
        projection=build_projection(balances,[],[],[],settings,today)
        result=build([{'date':today,'amount':2000}],[],balances,projection,settings,None,today)
        self.assertFalse(result['valid']);self.assertEqual(result['reserve']['hsbc_gap'],100)
        settings['hsbc_emergency_reserve']=100
        projection=build_projection(balances,[],[],[],settings,today,bank_status='partial')
        self.assertIsNone(build([{'date':today,'amount':2000}],[],balances,projection,settings,None,today)['available'])

    def test_missing_salary_and_no_future_salary_added(self):
        today=date(2026,10,4);balances={'HSBC':{'available':1000},'MONZO':{'available':0}}
        settings={'runway_daily_spend':10}
        projection=build_projection(balances,[],[],[],settings,today)
        result=build([{'date':date(2026,10,5),'amount':5000}],[],balances,projection,settings,None,today)
        self.assertFalse(result['valid']);self.assertEqual(result['received'],0)
        self.assertEqual(projection['cash'],1000)
