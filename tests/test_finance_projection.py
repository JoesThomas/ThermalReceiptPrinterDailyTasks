import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from finance.projection import build_projection, payment_schedule
from web_control.finance_suggestions import build_suggestions, dismiss_suggestion


class ProjectionTests(unittest.TestCase):
    today = date(2026, 9, 1)
    balances = {'HSBC': {'available': 1000}, 'MONZO': {'available': 0}}

    def project(self, monthly=(), yearly=(), transactions=(), settings=None, **kwargs):
        return build_projection(self.balances, list(transactions), list(monthly), list(yearly),
                                settings or {'runway_daily_spend': 10}, self.today, **kwargs)

    def test_large_upcoming_bill_changes_runway_on_its_actual_date(self):
        result = self.project([{'name': 'Bill', 'amount': 900, 'due_day': 3}], savings=500)
        self.assertEqual(result['cash_days'], 11)
        self.assertEqual(result['total_days'], 32)
        self.assertEqual(result['timeline'][2]['cash'], Decimal('80.00'))

    def test_paid_monthly_skipped_but_next_month_is_included(self):
        events, _, _ = payment_schedule([{'name': 'Bill', 'amount': 100, 'due_day': 31, 'paid': True}],
                                        [], [], {}, date(2026, 9, 30))
        self.assertEqual(events[0]['date'], date(2026, 10, 31))
        self.assertEqual(events[1]['date'], date(2026, 11, 30))
        self.assertEqual(events[2]['date'], date(2026, 12, 31))

    def test_estimated_rent_and_sky_do_not_create_an_extra_overdue_reserve(self):
        today=date(2026,10,11)
        monthly=[{'name':'Rent','amount':750,'last_paid':'2026-09-10'},
                 {'name':'Sky','amount':'32.36','last_paid':'2026-09-08'}]
        events,_,_=payment_schedule(monthly,[],[],{},today,horizon=60)
        first_period=[event for event in events if event['date']<=date(2026,11,10)]
        self.assertEqual([(event['name'],event['date'],event['amount']) for event in first_period],
                         [('Sky',date(2026,11,8),Decimal('32.36')),('Rent',date(2026,11,10),Decimal(750))])
        self.assertTrue(all(event['basis']=='Estimated from last payment' for event in first_period))
        self.assertEqual([event['date'] for event in events if event['name']=='Rent'],
                         [date(2026,11,10),date(2026,12,10)])

    def test_observed_payment_estimate_rolls_forward_even_without_paid_flag(self):
        events,_,_=payment_schedule([{'name':'Rent','amount':750,'match':['rent']}],[],
                                    [{'date':'2026-10-10','description':'Rent','amount':-750}],
                                    {},date(2026,10,11),horizon=31)
        self.assertEqual([(event['date'],event['amount']) for event in events],
                         [(date(2026,11,10),Decimal(750))])

    def test_configured_overdue_payment_and_unknown_date_still_reserve_today(self):
        today=date(2026,10,11)
        monthly=[{'name':'Confirmed date','amount':750,'next_payment':'2026-10-10'},
                 {'name':'Unknown date','amount':20}]
        events,undated,_=payment_schedule(monthly,[],[],{},today,horizon=1)
        self.assertEqual([event['date'] for event in events],[today,today])
        self.assertEqual(undated,['Unknown date'])

    def test_test_receipt_counts_one_rent_in_first_pay_period(self):
        from finance.test_receipt import build, receipt
        today=date(2026,10,11)
        events,_,_=payment_schedule([{'name':'Rent','amount':750,'last_paid':'2026-09-10'}],[],[],{},today)
        source={'valid':True,'cash':Decimal(100),'buffer':Decimal(100),'daily':Decimal(0),'warnings':[],'events':events}
        result=build(source,{'salary':'2000','start':str(today),'months':'1','save_all':'on'},today)
        self.assertEqual(result['bills_total'],750)
        self.assertEqual(result['forecast']['payments'][0]['savings'],1250)
        self.assertEqual(len(result['bills']),1)
        text=receipt(result,today)
        self.assertIn('Keep for bills / regular payments',text)
        self.assertIn('GBP 750.00',text)
        self.assertNotIn('Rent',text)
        self.assertNotIn('UPCOMING PAYMENTS',text)
        self.assertNotIn('11 Oct Rent [R]',text)
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_annual_renewal_paid_early_not_counted_again(self):
        annual = [{'name': 'Annual service', 'amount': 250, 'renewal_date': '2026-09-05', 'match': ['annual service']}]
        tx = [{'date': '2026-08-30', 'amount': -250, 'description': 'Annual service'}]
        result = self.project(yearly=annual, transactions=tx)
        self.assertFalse(result['upcoming'])
        unpaid = self.project(yearly=annual)
        self.assertEqual(unpaid['upcoming'][0]['date'], date(2026, 9, 5))

    def test_unknown_dates_are_reserved_and_partial_bank_data_withholds_days(self):
        result = self.project([{'name': 'Bill', 'amount': 100}])
        self.assertEqual(result['undated'], ['Bill'])
        self.assertTrue(result['upcoming'][0]['undated'])
        partial = self.project(bank_status='partial')
        self.assertIsNone(partial['cash_days'])
        self.assertFalse(partial['valid'])
        missing = build_projection({}, [], [], [], {'runway_daily_spend': 10}, self.today)
        self.assertIsNone(missing['cash'])
        self.assertIsNone(missing['cash_days'])

    def test_repayments_stop_at_remaining_balance_and_contracts_stop(self):
        plans = [{'name': 'Plan', 'amount': 50, 'remaining_balance': 120, 'next_payment': '2026-09-10'},
                 {'name': 'Contract', 'amount': 20, 'due_day': 15, 'end_date': '2026-09-20'}]
        events, _, _ = payment_schedule(plans, [], [], {}, self.today)
        self.assertEqual([e['amount'] for e in events if e['name'] == 'Plan'], [Decimal('50'), Decimal('50'), Decimal('20')])
        self.assertEqual(len([e for e in events if e['name'] == 'Contract']), 1)

    def test_schedule_preserves_each_amount_and_does_not_extend_plan(self):
        events, _, _ = payment_schedule([{'name': 'Plan', 'amount': 50, 'schedule': [
            {'date': '2026-09-10', 'amount': 50}, {'date': '2026-10-10', 'amount': 20}]}], [], [], {}, self.today)
        self.assertEqual([(e['date'], e['amount']) for e in events],
                         [(date(2026, 9, 10), Decimal('50')), (date(2026, 10, 10), Decimal('20'))])

    def test_known_bills_are_not_in_variable_spending_and_manual_alias_deduplicates(self):
        tx = [{'date': '2026-08-31', 'amount': -300, 'description': 'Example service'},
              {'date': '2026-08-31', 'amount': -30, 'description': 'Everyday store'}]
        result = self.project([{'name': 'Service', 'amount': 300, 'match': ['example service']}],
                              transactions=tx, settings={'commitments': [
                                  {'name': 'Service', 'amount': 300, 'due_date': '2026-09-05', 'repeat': 'monthly'}]})
        self.assertEqual(result['daily'], Decimal('1.00'))
        self.assertEqual(len(result['upcoming']), 1)
        self.assertEqual(result['upcoming'][0]['date'], date(2026, 9, 5))

    def test_amazon_shopping_excluded_from_daily_estimate_but_repayments_remain(self):
        transactions = [
            {'date': '2026-08-31', 'amount': -120, 'description': 'AMAZON.CO.UK AMAZON.CO.UK'},
            {'date': '2026-08-31', 'amount': -60, 'description': 'AMZNMKTPLACE*ORDER AMAZON.CO.UK'},
            {'date': '2026-08-31', 'amount': -30, 'description': 'Everyday store'},
        ]
        result = self.project(transactions=transactions, settings={'commitments': [
            {'name': 'Amazon repayment', 'amount': 50, 'due_date': '2026-09-05', 'repeat': 'monthly'}]})
        self.assertEqual(result['daily'], Decimal('1.00'))
        self.assertTrue(any(event['amount'] == Decimal('50') for event in result['upcoming']))
        from web_control.payments import external_payments
        self.assertEqual(sum(tx['spend_amount'] for tx in external_payments(transactions)), 210)

    def test_future_salary_not_counted_and_missing_card_repayment_flagged(self):
        result = self.project(settings={'runway_daily_spend': 10, 'forecast_events': [
            {'name': 'Salary', 'date': '2026-09-02', 'amount': 10000}]})
        self.assertEqual(result['cash_days'], 101)
        card = build_projection({**self.balances, 'AMEX': {'current': 500}}, [], [], [],
                                {'runway_daily_spend': 10}, self.today)
        self.assertFalse(card['valid'])
        self.assertTrue(any('Amex' in warning for warning in card['warnings']))

    def test_buffer_and_before_payday_include_listed_payments(self):
        result = self.project([{'name': 'Bill', 'amount': 500, 'due_day': 3}],
                              settings={'next_payday': '2026-09-11', 'emergency_buffer': 100, 'runway_daily_spend': 10})
        self.assertEqual(result['safe_before_payday'], Decimal('400.00'))
        self.assertEqual(result['per_day_before_payday'], Decimal('40.00'))

    def test_suggestions_are_evidenced_and_dismissals_stay_local(self):
        projection = self.project([{'name': 'Missing date', 'amount': 100}])
        with tempfile.TemporaryDirectory() as directory, patch('web_control.finance_suggestions.DISMISSED_FILE', Path(directory) / 'dismissed.json'):
            cards = build_suggestions(projection, [], [], [], {'categories': []}, [], [], self.today)
            card = next(c for c in cards if c['title'] == 'Add payment dates')
            self.assertEqual(card['evidence'], ['Missing date'])
            dismiss_suggestion(card['id'], self.today)
            remaining = build_suggestions(projection, [], [], [], {'categories': []}, [], [], self.today)
            self.assertNotIn(card['id'], [item['id'] for item in remaining])


if __name__ == '__main__':
    unittest.main()
