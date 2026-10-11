from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.test_receipt import build, receipt

TODAY=date(2026,10,11)


def source():
    return {'valid':True,'cash':D(1000),'buffer':D(420),'daily':D(0),'warnings':[],'events':[],
            'amex':{'balance':D(10000),'scheduled':True,'full_reserved':False},
            'reserve_details':{'target':D(500),'held':D(180),'gap':D(320),'date':date(2026,10,9),'tax_reserve':D(0)},
            'savings_accounts':[{'id':'cash','name':'Cash','kind':'savings','type':'savings','balance':D(220),
                                'date':'2026-10-10','target':D(500),'share':D(100),'isa_contributions':None}]}


def inputs():
    return {'salary':'100','start':str(TODAY),'months':'12','strategy':'amex_first','save_all':'on',
            'use_saved_accounts':'on','savings_goal':'500'}


class CashTopupGoalTests(TestCase):
    def test_reserved_cash_meets_goal_today_without_a_second_deduction(self):
        base=source();before=deepcopy(base)
        result=build(base,inputs(),TODAY)
        account=result['account_plan']['accounts'][0]
        self.assertEqual(result['projection']['buffer'],380)
        self.assertEqual(result['projection']['reserve_details']['gap'],280)
        self.assertEqual(account['balance'],220)
        self.assertEqual(account['first'],0)
        self.assertEqual(account['reserved_added'],280)
        self.assertEqual(account['automatic_added'],0)
        self.assertEqual(account['projected'],500)
        self.assertEqual(account['goal_date'],TODAY)
        self.assertEqual(result['forecast']['goal_date'],TODAY)
        self.assertEqual(result['forecast']['reserved_total'],280)
        self.assertEqual(result['forecast']['savings_end'],500)
        # Cash above reserves: 1000 - 380; each salary pays Amex, not the reserve again.
        self.assertEqual(result['forecast']['end_cash'],620)
        self.assertEqual(base,before)
        text=receipt(result,TODAY)
        self.assertIn('Projected target date: around October 2026',text)
        self.assertIn('Estimated time to target:\nNow',text)
        self.assertNotIn('11 Mar 2027',text)
        self.assertIn('Average ongoing additions / month',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_newer_physical_count_is_used_by_the_cash_goal_and_reserve(self):
        base=source();base['reserve_details']['date']=TODAY
        result=build(base,inputs(),TODAY)
        account=result['account_plan']['accounts'][0]
        self.assertEqual(account['balance'],180)
        self.assertEqual(account['date'],str(TODAY))
        self.assertEqual(account['reserved_added'],320)
        self.assertEqual(account['projected'],500)

    def test_different_cash_goal_is_only_partly_funded_by_the_reserve(self):
        base=source();base['reserve_details'].update(target=D(400),gap=D(220));base['buffer']=D(320)
        result=build(base,inputs(),TODAY)
        account=result['account_plan']['accounts'][0]
        self.assertEqual(account['reserved_added'],180)
        self.assertEqual(account['projected'],400)
        self.assertIsNone(account['goal_date'])

    def test_unfunded_topup_does_not_claim_the_goal_is_met_today(self):
        base=source();base['cash']=D(0)
        result=build(base,inputs(),TODAY)
        self.assertEqual(result['forecast']['reserved_total'],0)
        self.assertEqual(result['account_plan']['accounts'][0]['reserved_added'],0)
        self.assertNotEqual(result['account_plan']['accounts'][0]['goal_date'],TODAY)
        self.assertIn('Cash top-up - funding needed',receipt(result,TODAY))

    def test_ambiguous_cash_accounts_are_not_merged(self):
        base=source();base['savings_accounts'].append(dict(base['savings_accounts'][0],id='other',name='Physical cash',share=D(0)))
        result=build(base,inputs(),TODAY)
        self.assertNotIn('cash_topup',result['projection'])
        self.assertEqual(result['forecast']['reserved_total'],0)

    def test_disabled_account_allocation_does_not_credit_a_cash_goal(self):
        values=inputs();values['use_saved_accounts']=''
        result=build(source(),values,TODAY)
        self.assertEqual(result['forecast']['reserved_total'],0)

    def test_reserved_cash_topup_does_not_require_incoming_salary(self):
        settings=inputs();settings['salary']='0'
        result=build(source(),settings,TODAY)
        self.assertEqual(result['forecast']['savings_total'],0)
        self.assertEqual(result['forecast']['reserved_total'],280)
        self.assertEqual(result['account_plan']['accounts'][0]['goal_date'],TODAY)
