from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from finance.savings_targets import allocate
from finance.test_receipt import build, receipt
from finance import savings_goals as goals

TODAY=date(2026,10,10)


def account(name,balance,target,share='0',kind='savings'):
    return {'id':name,'name':name,'kind':kind,'type':'savings','balance':D(balance) if balance is not None else None,
            'date':'2026-10-10','target':D(target) if target is not None else None,'share':D(share),'isa_contributions':None}


class AccountGoalTests(TestCase):
    def test_shared_budget_caps_completed_goal_and_redistributes(self):
        rows=[account('Nearly done','90','100','50'),account('Longer goal','0','1000','50')]
        before=deepcopy(rows)
        periods=[{'date':TODAY,'savings':D(100)},{'date':date(2026,11,10),'savings':D(100)}]
        plan=allocate(rows,periods)
        self.assertEqual(plan['accounts'][0]['added'],10)
        self.assertEqual(plan['accounts'][1]['added'],190)
        self.assertEqual(plan['accounts'][0]['goal_date'],TODAY)
        self.assertEqual(plan['unallocated'],0)
        self.assertEqual(rows,before)

    def test_unassigned_and_missing_balances_are_not_invented(self):
        rows=[account('Goal','0','1000','50'),account('Unknown',None,'1000','50')]
        plan=allocate(rows,[{'date':TODAY,'savings':D(100)}])
        self.assertEqual(plan['accounts'][0]['added'],50)
        self.assertEqual(plan['unallocated'],50)
        self.assertFalse(plan['complete'])
        self.assertIsNone(plan['accounts'][1]['projected'])

    def test_equal_default_allocation_and_recorded_starting_total(self):
        rows=[account('First','90','100'),account('Second','0','1000')]
        source={'valid':True,'cash':D(100),'buffer':D(100),'daily':D(0),'events':[],'warnings':[], 'savings_accounts':rows}
        values={'salary':'100','start':str(TODAY),'months':'4','save_all':'on','use_saved_accounts':'on','starting_savings':'9999','savings_goal':'300'}
        result=build(source,values,TODAY)
        self.assertEqual(result['inputs']['starting_savings'],90)
        self.assertEqual(result['forecast']['savings_end'],490)
        self.assertEqual(result['account_plan']['projected_total'],490)
        self.assertEqual(result['account_plan']['accounts'][0]['projected'],100)
        self.assertEqual(result['account_plan']['accounts'][1]['projected'],390)
        self.assertEqual(result['forecast']['goal_date'],date(2026,12,10))
        text=receipt(result,TODAY)
        self.assertIn('RECORDED SAVINGS & INVESTMENTS',text)
        self.assertIn('Projected target date: 10 Oct 2026',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_target_shares_save_privately_and_excess_is_rejected(self):
        with TemporaryDirectory() as folder,patch.object(goals,'FILE',Path(folder)/'goals.json'):
            goals.account_settings('First','savings','savings','100','60')
            goals.account_settings('Second','investment','stocks_isa','1000','40')
            before=goals.load()
            with self.assertRaises(ValueError):goals.account_settings('Second','investment','stocks_isa','1000','50')
            self.assertEqual(goals.load(),before)
            with self.assertRaises(ValueError):goals.account_settings('Bonds','savings','premium_bonds','50001','0')
            goals.account_settings('First','savings','savings','200')
            self.assertEqual(goals.load()['accounts'][goals.identity('First','savings')]['monthly_share'],'60.00')

    def test_isa_balance_goal_is_separate_from_allowance_progress(self):
        key=goals.identity('ISA','investment')
        state={'accounts':{key:{'name':'ISA','kind':'investment','type':'stocks_isa','target':'10000','monthly_share':'100'}},'entries':[], 'years':{}}
        wealth={'accounts':[{'name':'ISA','kind':'investment','balance':D(5000),'latest':{'date':'2026-10-10'}}]}
        view=goals.review(wealth,state=state,on=TODAY,bond_balances=[])
        row=view['accounts'][0]
        self.assertEqual(row['balance_goal']['percent'],50)
        self.assertEqual(row['percent'],0)
        self.assertIn('ISA BALANCE GOAL',goals.receipt_lines(view))
