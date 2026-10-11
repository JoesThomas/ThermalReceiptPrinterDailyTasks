from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.test_receipt import build, receipt

TODAY=date(2026,10,11)


def source(cash='3000',buffer='0'):
    return {'valid':True,'cash':D(cash),'buffer':D(buffer),'daily':D(0),'warnings':[],
            'events':[{'date':date(2026,10,20),'name':'Rent','amount':D(500)}],
            'savings_accounts':[{'id':'isa','name':'ISA','kind':'investment','type':'stocks_isa',
                'balance':D(200),'date':str(TODAY),'target':D(10000),'share':D(100),'isa_contributions':D(0)}]}


def values(**overrides):
    return dict({'salary':'100','start':str(TODAY),'months':'1','savings_target':'0',
                 'use_saved_accounts':'on','invest_spare_cash':'on'},**overrides)


class SpareBankCashTests(TestCase):
    def test_salary_triggers_cash_investment_after_costs_and_bank_floor(self):
        base=source();before=deepcopy(base)
        result=build(base,values(),TODAY)
        forecast=result['forecast'];first=forecast['payments'][0]
        self.assertEqual(first['cash_invested'],1600)
        self.assertEqual(first['income_savings'],0)
        self.assertEqual(forecast['savings_total'],1600)
        self.assertEqual(forecast['end_cash'],0)
        self.assertIsNone(forecast['run_out'])
        self.assertEqual(result['projection']['buffer'],1000)
        self.assertEqual(result['account_plan']['accounts'][0]['first'],1600)
        self.assertEqual(result['account_plan']['accounts'][0]['projected'],1800)
        self.assertEqual(base,before)
        text=receipt(result,TODAY)
        self.assertIn('ISA',text)
        self.assertIn('£1,600.00',text)
        self.assertIn('Spare bank cash invested over forecast',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_disabling_option_retains_existing_income_only_behavior(self):
        result=build(source(),values(invest_spare_cash=''),TODAY)
        self.assertEqual(result['forecast']['savings_total'],0)
        self.assertEqual(result['forecast']['end_cash'],2600)
        self.assertEqual(result['projection']['buffer'],0)

    def test_daily_spending_and_higher_bank_reserve_are_protected(self):
        base=source(buffer='1500');base['daily']=D(10)
        result=build(base,values(),TODAY)
        self.assertEqual(result['forecast']['cash_invested_total'],790)
        self.assertEqual(result['projection']['buffer'],1500)
        self.assertEqual(result['forecast']['end_cash'],0)
        self.assertIsNone(result['forecast']['run_out'])

    def test_cash_below_floor_does_not_create_a_transfer(self):
        result=build(source(cash='900'),values(),TODAY)
        self.assertEqual(result['forecast']['cash_invested_total'],0)
        self.assertEqual(result['forecast']['savings_total'],0)
        self.assertIsNotNone(result['forecast']['run_out'])

    def test_scheduled_savings_are_reserved_and_credited_once(self):
        base=source();base['events'].append({'name':'ISA','date':date(2026,10,15),'amount':D(25),'category':'savings'})
        result=build(base,values(),TODAY)
        self.assertEqual(result['forecast']['cash_invested_total'],1575)
        self.assertEqual(result['forecast']['automatic_total'],25)
        self.assertEqual(result['forecast']['savings_end'],1800)
        self.assertEqual(result['forecast']['end_cash'],0)

    def test_goal_date_uses_spare_cash_on_the_first_payday(self):
        base=source();base['savings_accounts'][0]['target']=D(1700)
        result=build(base,values(savings_goal='1700'),TODAY)
        self.assertEqual(result['account_plan']['accounts'][0]['goal_date'],TODAY)
        self.assertEqual(result['forecast']['goal_date'],TODAY)

    def test_amex_first_uses_income_and_spare_bank_cash_before_savings(self):
        base=source();base['amex']={'balance':D(5000),'full_reserved':False}
        result=build(base,values(salary='1000',strategy='amex_first'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'],2500)
        self.assertEqual(first['cash_repaid'],2000)
        self.assertEqual(first['cash_invested'],0)
        self.assertEqual(first['savings'],0)
        self.assertEqual(result['account_plan']['accounts'][0]['first'],0)
        text=' '.join(receipt(result,TODAY).split())
        self.assertIn('Includes £2,000.00 from spare bank cash in the Amex repayment above.',text)
        self.assertEqual(result['forecast']['end_cash'],0)

    def test_future_periods_do_not_transfer_the_starting_cash_twice(self):
        result=build(source(),values(salary='100',months='2'),TODAY)
        self.assertEqual([p['cash_invested'] for p in result['forecast']['payments']],[1600,100])
        self.assertEqual([p['income_savings'] for p in result['forecast']['payments']],[0,0])
        self.assertEqual(result['forecast']['end_cash'],0)

    def test_lump_sum_is_not_invested_without_salary(self):
        result=build(source(cash='1000'),values(mode='lump',lump_sum='2000'),TODAY)
        self.assertEqual(result['forecast']['cash_invested_total'],0)
        self.assertEqual(result['forecast']['end_cash'],2500)

    def test_cash_and_tax_reserves_are_in_addition_to_bank_floor(self):
        base=source(buffer='500')
        base['reserve_details']={'gap':D(200),'tax_reserve':D(300)}
        result=build(base,values(),TODAY)
        self.assertEqual(result['projection']['buffer'],1500)
        self.assertEqual(result['forecast']['cash_invested_total'],1100)
        self.assertEqual(result['forecast']['end_cash'],0)

    def test_cash_sweep_rounds_down_to_avoid_spending_a_fractional_penny(self):
        base=source(cash='3000.005')
        result=build(base,values(),TODAY)
        self.assertEqual(result['forecast']['cash_invested_total'],D('1600.00'))
        self.assertEqual(result['forecast']['end_cash'],D('0.005'))

    def test_reserved_cash_topup_and_bank_investment_are_counted_separately(self):
        base=source();base['buffer']=D(200)
        base['reserve_details']={'target':D(500),'held':D(300),'gap':D(200),'tax_reserve':D(0),'date':TODAY}
        base['savings_accounts'].append({'id':'cash','name':'Cash','kind':'savings','type':'savings',
            'balance':D(300),'date':str(TODAY),'target':D(500),'share':D(0),'isa_contributions':None})
        result=build(base,values(),TODAY)
        self.assertEqual(result['forecast']['reserved_total'],200)
        self.assertEqual(result['forecast']['cash_invested_total'],1400)
        self.assertEqual(result['forecast']['savings_end'],2100)
        self.assertEqual(result['account_plan']['accounts'][1]['projected'],500)
        self.assertEqual(result['projection']['buffer'],1200)

    def test_no_salary_keeps_existing_cash_even_with_other_income(self):
        for other in ('0','1000'):
            result=build(source(),values(salary='0',other_income=other),TODAY)
            self.assertEqual(result['forecast']['cash_invested_total'],0)
            self.assertEqual(result['projection']['buffer'],0)
            self.assertIn('spare bank cash investment paused.',' '.join(receipt(result,TODAY).split()))

    def test_additional_existing_salary_counts_as_salary_for_the_cash_transfer(self):
        result=build(source(),values(salary='0',mode='additional',existing_salary='100'),TODAY)
        self.assertEqual(result['forecast']['cash_invested_total'],1600)

    def test_amex_first_only_saves_money_left_after_card_is_fully_reserved(self):
        base=source();base['amex']={'balance':D(1200),'full_reserved':False}
        base['events'].append({'name':'Amex payment','amount':D(50),'date':date(2026,10,25)})
        result=build(base,values(salary='1000',strategy='amex_first',save_all='on'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'],1150)
        self.assertEqual(first['savings'],1300)
        self.assertEqual(first['cash_repaid'],700)
        self.assertEqual(result['forecast']['card_end'],0)
        self.assertEqual(result['forecast']['end_cash'],0)

    def test_split_strategy_includes_spare_cash_in_the_split(self):
        base=source();base['amex']={'balance':D(5000),'full_reserved':False}
        result=build(base,values(salary='1000',strategy='split',amex_split='50',save_all='on'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'],1250)
        self.assertEqual(first['savings'],1250)
        self.assertEqual(first['cash_repaid'],750)
        self.assertEqual(first['cash_invested'],1250)
        self.assertEqual(result['forecast']['end_cash'],0)

    def test_quoted_receipt_amounts_go_to_amex_first_without_extra_savings(self):
        base=source(cash='3541.90',buffer='1000');base['daily']=D('55.91806451612903225806451613')
        base['events']=[{'name':'Bills','amount':D('1406.03'),'date':date(2026,10,20)}]
        base['amex']={'balance':D(10000),'full_reserved':False}
        result=build(base,values(salary='3900',strategy='amex_first',save_all='on'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'],D('3302.41'))
        self.assertEqual(first['cash_repaid'],D('2541.90'))
        self.assertEqual(first['savings'],0)
        self.assertEqual(result['account_plan']['accounts'][0]['first'],0)

    def test_runway_shows_bank_reserve_separately_from_money_above_it(self):
        for buffer,expected in [('0','£1,000.00'),('1500','£1,500.00')]:
            base=source(buffer=buffer)
            result=build(base,values(),TODAY)
            text=receipt(result,TODAY).split('RUNWAY WITH TEST INCOME')[1]
            reserve_line=next(line for line in text.splitlines() if 'Bank reserve kept' in line)
            self.assertIn(expected,reserve_line)
            self.assertIn('Bank cash above reserves at end',text)
            self.assertTrue(all(len(line)<=42 for line in text.splitlines()))
