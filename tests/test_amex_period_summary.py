from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.test_receipt import build, receipt

TODAY=date(2026,10,11)


def source():
    return {'valid':True,'cash':D('3541.90'),'buffer':D(1000),'daily':D(0),'warnings':[],
            'amex':{'balance':D('3549.94'),'full_reserved':False,'apr':D(0)},
            'events':[{'name':'Bills','amount':D('3089.49'),'date':date(2026,10,20)},
                      {'name':'Amex payment','amount':D(50),'date':date(2026,10,25)},
                      {'name':'Amex payment','amount':D(50),'date':date(2026,11,25)}]}


def values(**changes):
    return dict({'salary':'3900','start':str(TODAY),'months':'2','strategy':'amex_first',
                 'invest_spare_cash':'on','save_all':'on'},**changes)


class AmexPeriodSummaryTests(TestCase):
    def test_user_figures_show_complete_current_and_forecast_repayments(self):
        result=build(source(),values(),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'],D('3302.41'))
        self.assertEqual(first['closing_card'],D('197.53'))
        self.assertEqual(result['forecast']['extra_total'],D('3449.94'))
        self.assertEqual(result['forecast']['payoff'],date(2026,11,25))
        text=receipt(result,TODAY).split('AMEX PLAN')[1].split('SAVINGS PROJECTION')[0]
        period,forecast=text.split('WHOLE FORECAST')
        for label,value in [('Balance at period start','£3,549.94'),
                            ('Scheduled repayment this period','£50.00'),
                            ('Extra repayment this period','£3,302.41'),
                            ('Balance at period end','£197.53')]:
            self.assertIn(label,period)
            self.assertIn(value,period)
        self.assertIn('Scheduled repayments over forecast',forecast)
        self.assertIn('£100.00',forecast)
        self.assertIn('£3,449.94',forecast)
        self.assertNotIn('Savings redirected',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_delayed_payday_uses_card_balance_after_prior_scheduled_payment(self):
        result=build(source(),values(start='2026-11-11'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['opening_card'],D('3499.94'))
        text=receipt(result,TODAY).split('THIS PAY PERIOD')[1].split('WHOLE FORECAST')[0]
        self.assertIn('£3,499.94',text)
        self.assertNotIn('£3,549.94',text)

    def test_interest_reconciles_the_period_balance(self):
        result=build(source(),values(amex_apr='24'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertGreater(first['closing_card'],D('197.53'))
        text=receipt(result,TODAY).split('THIS PAY PERIOD')[1].split('WHOLE FORECAST')[0]
        self.assertIn('Estimated interest this period',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))
