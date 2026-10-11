from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.test_receipt import build, receipt
from finance.savings_targets import link_regular_savings

TODAY=date(2026,10,10)


def account(name,target,share):
    return {'id':name,'name':name,'kind':'savings','type':'savings','balance':D(0),'date':str(TODAY),
            'target':D(target),'share':D(share),'isa_contributions':None}


def source():
    return {'valid':True,'cash':D(100),'buffer':D(100),'daily':D(0),'warnings':[],
            'events':[{'name':'Hargreaves Lansdown','amount':D(25),'category':'savings','date':date(2026,month,7)} for month in (11,12)],
            'savings_accounts':[account('NS and I','1000','100'),account('H and L','50','0')]}


def values(**kwargs):
    return dict(salary='100',start=str(TODAY),months='2',savings_target='100',use_saved_accounts='on',savings_goal='100',**kwargs)


class IncomeTransferTests(TestCase):
    def test_regular_saving_is_reserved_once_and_credited_on_its_due_date(self):
        base=source();before=deepcopy(base)
        result=build(base,values(),TODAY)
        forecast=result['forecast'];plan=result['account_plan']
        self.assertEqual(forecast['savings_total'],150)
        self.assertEqual(forecast['automatic_total'],50)
        self.assertEqual(forecast['savings_end'],200)
        self.assertEqual(forecast['goal_date'],date(2026,11,7))
        self.assertEqual(forecast['end_cash'],0)
        self.assertEqual(plan['accounts'][0]['first'],75)
        self.assertEqual(plan['accounts'][1]['first'],0)
        self.assertEqual(plan['accounts'][1]['first_automatic'],25)
        self.assertEqual(plan['accounts'][1]['projected'],50)
        self.assertEqual(plan['accounts'][1]['goal_date'],date(2026,12,7))
        self.assertEqual(plan['projected_total'],forecast['savings_end'])
        self.assertEqual(base,before)
        text=receipt(result,TODAY)
        summary=text.split('WHERE TO MOVE THIS PAYDAY')[1].split('CASH & RESERVES')[0]
        self.assertIn('NS and I',summary)
        self.assertIn('£75.00',summary)
        self.assertIn('Already scheduled - do not send again:',summary)
        self.assertIn('07 Nov Hargreaves Lansdown',summary)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_save_all_keeps_automatic_saving_in_costs_without_double_deduction(self):
        result=build(source(),values(save_all='on'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['costs'],25)
        self.assertEqual(first['savings'],75)
        self.assertEqual(first['automatic_savings'],25)
        self.assertEqual(first['costs']+first['savings'],100)

    def test_regular_payment_larger_than_target_requires_no_extra_transfer(self):
        inputs=values();inputs['savings_target']='10'
        result=build(source(),inputs,TODAY)
        self.assertEqual(result['forecast']['savings_total'],0)
        self.assertEqual(result['forecast']['automatic_total'],50)
        self.assertIn('No extra transfers in this period.',receipt(result,TODAY))

    def test_ambiguous_hl_accounts_do_not_receive_an_invented_credit(self):
        events=source()['events']
        accounts=[account('H and L','100','50'),account('Hargreaves Lansdown','100','50')]
        link_regular_savings(events,accounts)
        self.assertFalse(any('savings_account' in event for event in events))

    def test_physical_cash_topup_is_shown_as_already_reserved(self):
        base=source();base['reserve_details']={'gap':D(5),'tax_reserve':D(0)}
        text=receipt(build(base,values(),TODAY),TODAY)
        self.assertIn('Cash top-up (already reserved)',text)
        self.assertIn('£5.00',text)

    def test_hlam_alias_is_linked_without_hardcoding_the_payment_amount(self):
        events=[{'name':'HLAM Regular Saving','amount':D(30),'date':TODAY}]
        link_regular_savings(events,[account('H and L','100','100')])
        self.assertEqual(events[0]['savings_account'],'H and L')

    def test_compact_receipt_keeps_bill_total_without_individual_bills(self):
        base=source()
        base['events'].append({'name':'Rent','amount':D(20),'date':date(2026,10,15)})
        result=build(base,values(),TODAY)
        text=receipt(result,TODAY)
        summary=text.split('WHERE TO MOVE THIS PAYDAY')[1].split('CASH & RESERVES')[0]
        self.assertIn('£45.00',summary)
        self.assertNotIn('Rent',text)
        self.assertNotIn('UPCOMING PAYMENTS',text)
        self.assertIn('07 Nov Hargreaves Lansdown',summary)
        self.assertEqual(text.count('Keep for bills / regular payments'),1)
        self.assertNotIn('Extra transfer this period',text)
        self.assertNotIn('No other confirmed repayment balances.',text)
        self.assertLess(text.index('WHERE TO MOVE THIS PAYDAY'),text.index('RECORDED SAVINGS'))
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_zero_income_does_not_use_bank_cash_for_extra_savings(self):
        base=source();base['cash']=D(1000)
        settings=values();settings['salary']='0'
        result=build(base,settings,TODAY)
        self.assertEqual(result['forecast']['savings_total'],0)
        self.assertEqual(result['forecast']['automatic_total'],50)
        self.assertEqual(result['account_plan']['accounts'][1]['goal_date'],date(2026,12,7))
        text=' '.join(receipt(result,TODAY).split())
        self.assertIn('existing bank cash is not used for extra savings.',text)

    def test_other_recurring_income_can_fund_extra_savings_without_salary(self):
        settings=values();settings.update(salary='0',other_income='100')
        result=build(source(),settings,TODAY)
        self.assertEqual(result['forecast']['savings_total'],150)
        self.assertEqual(result['forecast']['automatic_total'],50)
