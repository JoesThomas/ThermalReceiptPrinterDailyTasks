from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.test_receipt import build, receipt

TODAY=date(2026,10,11)


def account(name,share=0,balance=D(0),target=D(1000)):
    return {'id':name,'name':name,'kind':'investment','type':'stocks_isa','balance':balance,
            'date':str(TODAY),'target':target,'share':D(share),'isa_contributions':D(0)}


def source():
    return {'valid':True,'cash':D(1000),'buffer':D(1000),'daily':D(0),'warnings':[],'events':[],
            'savings_accounts':[account('NS and I',50),account('H and L',50),account('New ISA 1'),account('New ISA 2')]}


def values(**changes):
    return dict({'salary':'100','start':str(TODAY),'months':'1','save_all':'on',
                 'use_saved_accounts':'on','equal_savings':'on'},**changes)


class EqualSavingsTests(TestCase):
    def test_two_new_accounts_join_equal_split_without_editing_saved_shares(self):
        base=source();before=deepcopy(base)
        result=build(base,values(),TODAY)
        self.assertEqual([r['first'] for r in result['account_plan']['accounts']],[D(25)]*4)
        self.assertEqual(result['account_plan']['unallocated'],0)
        self.assertEqual(base,before)
        self.assertEqual([r['share'] for r in result['account_plan']['accounts']],[D(50),D(50),D(0),D(0)])
        text=receipt(result,TODAY)
        self.assertIn('Savings split: equal between active goals.',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_custom_shares_remain_available(self):
        result=build(source(),values(equal_savings=''),TODAY)
        self.assertEqual([r['first'] for r in result['account_plan']['accounts']],[50,50,0,0])

    def test_completed_missing_or_untargeted_accounts_do_not_take_a_share(self):
        base=source()
        base['savings_accounts']=[account('Done',50,balance=D(1000)),account('Missing',50,balance=None),
                                 account('No target',target=None),account('Active')]
        result=build(base,values(),TODAY)
        self.assertEqual([r['first'] for r in result['account_plan']['accounts']],[0,0,0,100])
        self.assertEqual(result['account_plan']['unallocated'],0)

    def test_a_nearly_complete_goal_redistributes_its_excess(self):
        base=source();base['savings_accounts']=[account('Small',target=D(10)),account('Large 1'),account('Large 2')]
        result=build(base,values(),TODAY)
        self.assertEqual([r['first'] for r in result['account_plan']['accounts']],[10,45,45])
        self.assertEqual(result['account_plan']['unallocated'],0)

    def test_pennies_are_allocated_once(self):
        base=source();base['savings_accounts']=base['savings_accounts'][:3]
        result=build(base,values(),TODAY)
        shares=[r['first'] for r in result['account_plan']['accounts']]
        self.assertEqual(sum(shares),100)
        self.assertLessEqual(max(shares)-min(shares),D('.01'))

    def test_regular_hl_payment_stays_separate_from_equal_extra_transfers(self):
        base=source();base['events']=[{'name':'Hargreaves Lansdown','amount':D(25),'category':'savings','date':date(2026,11,7)}]
        result=build(base,values(),TODAY)
        self.assertEqual([r['first'] for r in result['account_plan']['accounts']],[D('18.75')]*4)
        self.assertEqual(result['account_plan']['accounts'][1]['automatic_added'],25)
        self.assertEqual(result['forecast']['savings_end'],100)

    def test_amex_first_still_precedes_equal_savings(self):
        base=source();base['amex']={'balance':D(1000),'full_reserved':False}
        result=build(base,values(strategy='amex_first'),TODAY)
        self.assertEqual(result['forecast']['payments'][0]['extra'],100)
        self.assertEqual([r['first'] for r in result['account_plan']['accounts']],[0,0,0,0])

    def test_extended_goal_dates_use_equal_split_too(self):
        base=source();base['savings_accounts']=[account('Old',100,target=D(50)),account('New',0,target=D(50))]
        result=build(base,values(salary='50'),TODAY)
        self.assertEqual([r['extended_goal_date'] for r in result['account_plan']['accounts']],[date(2026,11,11)]*2)
