from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.test_receipt import build, receipt, validate

TODAY=date(2026,10,10)


def source(balance='5000'):
    return {'valid':True,'cash':D(100),'buffer':D(100),'daily':D(0),'warnings':[],
        'amex':{'balance':D(balance),'full_reserved':False,'scheduled':True},
        'events':[{'name':'Amex payment','date':date(2026,m,25),'amount':D(50)} for m in (10,11,12)]}


def values(**extra):
    return dict(salary='1000',other_income='0',start=str(TODAY),months='3',save_all='on',**extra)


class DailyFinanceTests(TestCase):
    def test_strategies_use_each_pound_once(self):
        for strategy,extra,saving in [('amex_first',950,0),('savings_first',0,950),('split',475,475)]:
            result=build(source(),values(strategy=strategy),TODAY)
            period=result['forecast']['payments'][0]
            self.assertEqual(period['extra'],extra)
            self.assertEqual(period['savings'],saving)
            self.assertEqual(period['extra']+period['savings']+period['costs'],1000)
            self.assertEqual(result['forecast']['end_cash'],0)

    def test_payoff_stops_future_payments_and_savings_increase(self):
        base=source('150'); before=deepcopy(base)
        base['events'] += [{'name':'Finite instalment','date':date(2026,m,15),'amount':D(200)} for m in (10,11)]
        result=build(base,values(strategy='amex_first',savings_goal='1400'),TODAY)
        periods=result['forecast']['payments']
        self.assertEqual([p['savings'] for p in periods],[D(650),D(800),D(1000)])
        self.assertEqual(result['forecast']['payoff'],date(2026,10,25))
        self.assertEqual(result['forecast']['card_end'],0)
        self.assertEqual(result['forecast']['savings_total'],2450)
        self.assertEqual(result['forecast']['goal_date'],date(2026,11,10))
        card_events=[e for e in result['forecast']['events'] if 'Amex' in e['name']]
        self.assertEqual(len(card_events),1)
        self.assertEqual(before['amex'],base['amex'])
        text=receipt(result,TODAY)
        self.assertLess(text.index('PAY PERIOD ALLOCATION'),text.index('CASH & RESERVES'))
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_interest_delays_payoff_and_is_accounted_for(self):
        no_interest=build(source('150'),values(strategy='amex_first',amex_apr='0'),TODAY)
        interest=build(source('150'),values(strategy='amex_first',amex_apr='24'),TODAY)
        self.assertGreater(interest['forecast']['interest'],0)
        self.assertGreater(interest['forecast']['payoff'],no_interest['forecast']['payoff'])
        self.assertLess(interest['forecast']['savings_total'],no_interest['forecast']['savings_total'])
        self.assertEqual(interest['forecast']['card_end'],0)

    def test_goal_date_can_extend_beyond_selected_forecast(self):
        result=build(source('0'),values(strategy='savings_first',savings_goal='20000'),TODAY)
        self.assertIsNone(result['forecast']['goal_date'])
        self.assertEqual(result['forecast']['extended_goal_date'],date(2028,5,10))
        self.assertIn('Extended projected goal date:',receipt(result,TODAY))
        self.assertEqual(result['forecast']['savings_end'],3000)
        text=receipt(result,TODAY)
        self.assertIn('Goal progress now: 0.0%', text)
        self.assertIn('Projected progress at forecast end: 15.0%', ' '.join(text.split()))
        self.assertIn('Estimated time to target:\n1 year and 7 months (578 days)', text)
        self.assertIn('Beyond selected forecast; same pathway.', text)

    def test_extended_pathway_starts_saving_after_initial_debt_only_periods(self):
        result=build(source(),values(strategy='amex_first',savings_goal='1000'),TODAY)
        self.assertEqual(result['forecast']['savings_total'],0)
        self.assertIsNotNone(result['forecast']['extended_goal_date'])
        text=receipt(result,TODAY)
        self.assertIn('no savings added in the selected forecast.', ' '.join(text.split()))
        self.assertIn('Extended projected goal date:', text)
        self.assertIn('Estimated time to target:', text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_progress_uses_starting_balance_and_handles_already_met_or_unfunded(self):
        settings=values(strategy='savings_first',starting_savings='30000',savings_goal='50000')
        result=build(source('0'),settings,TODAY)
        text=receipt(result,TODAY)
        self.assertIn('Goal progress now: 60.0%',text)
        self.assertIn('Projected progress at forecast end: 66.0%', ' '.join(text.split()))
        settings['savings_goal']='20000'
        text=receipt(build(source('0'),settings,TODAY),TODAY)
        self.assertIn('target already reached.',text)
        self.assertNotIn('Estimated time to target:',text)
        settings.update(savings_goal='50000',salary='0')
        base=source('0');base['daily']=D(10)
        text=receipt(build(base,settings,TODAY),TODAY)
        self.assertIn('pathway has a funding shortfall.', ' '.join(text.split()))
        self.assertNotIn('Estimated time to target:',text)

    def test_invalid_rate_strategy_and_split(self):
        for field,value in [('amex_apr','NaN'),('amex_apr','-1'),('strategy','bad'),('amex_split','101')]:
            with self.assertRaises(ValueError): validate(values(**{field:value}),TODAY)
