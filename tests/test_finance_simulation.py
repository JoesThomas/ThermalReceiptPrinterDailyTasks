from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from flask import Flask
from finance.test_receipt import build, receipt, validate
from web_control.test_finance_tools import register

TODAY = date(2026, 10, 10)


def projection():
    return {'valid': True, 'cash': D('1200'), 'buffer': D('1000'), 'daily': D('10'),
            'daily_cost': D('10'), 'warnings': [], 'events': [
                {'date': date(2026, 10, 15), 'name': 'Rent', 'amount': D('750')}]}


def inputs(**extra):
    return dict(salary='4500', existing_salary='2000', other_income='800',
                savings_target='1000', mode='replace', start='2026-10-10', months='2', **extra)


class SimulationTests(TestCase):
    def test_replacement_does_not_add_existing_salary_or_mutate_projection(self):
        source = projection(); before = deepcopy(source)
        result = build(source, inputs(), TODAY)
        self.assertEqual(result['inputs']['existing'], D(0))
        self.assertEqual(result['payday_cash'], D('6500'))
        self.assertEqual(result['bills_total'], D('750'))
        self.assertEqual(result['savings'], D('1000'))
        self.assertEqual(source, before)
        text = receipt(result, TODAY)
        self.assertIn('SIMULATION - POTENTIAL SALARY', text)
        self.assertIn('GBP 4,500.00', text)
        self.assertNotIn('Existing salary (additional mode)', text)
        self.assertEqual(result['forecast']['payments'][0]['salary'], D('4500'))
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))

    def test_repayment_options_and_monthly_savings_are_explicit(self):
        source = projection()
        source['repayment_options'] = [{'name': 'Amex', 'balance': '500', 'apr': '24'},
            {'name': 'Roland', 'remaining_balance': '1000', 'amount': '124.92', 'end_date': '2027-06-01'}]
        values = inputs()
        result = build(source, values, TODAY)
        text = receipt(result, TODAY)
        self.assertIn('Potential full payoff', text)
        self.assertIn('Per day (expected spending)', text)
        self.assertIn('Test savings transfers over forecast', text)
        self.assertIn('Bank cash excludes transferred savings.', text)
        self.assertIn('Confirm balance/rate', text)
        self.assertIn('Final payment: 01 Jun 2027', text)
        without = dict(values, savings_target='0')
        self.assertEqual(build(source, without, TODAY)['forecast']['end_cash'] - result['forecast']['end_cash'], D('2000'))
        self.assertIn('Savings target not set', receipt(build(source, without, TODAY), TODAY))
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))

    def test_lump_sum_arrives_once_and_ignores_all_recurring_income(self):
        values = inputs(); values.update(mode='lump', lump_sum='10000')
        result = build(projection(), values, TODAY)
        self.assertEqual(result['payday_cash'], D('11200'))
        self.assertEqual(result['inputs']['salary'], D(0))
        self.assertEqual(result['inputs']['other'], D(0))
        self.assertEqual(result['monthly_savings'], D(0))
        zero = dict(values, lump_sum='0')
        self.assertEqual(result['forecast']['end_cash'] - build(projection(), zero, TODAY)['forecast']['end_cash'], D('10000'))
        text = receipt(result, TODAY)
        self.assertIn('SIMULATION - LUMP SUM ONLY', text)
        self.assertNotIn('GBP 4,500.00', text)
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))
        values['start'] = '2026-11-10'
        self.assertLess(build(projection(), values, TODAY)['forecast']['run_out'], date(2026, 11, 10))
        values['lump_sum'] = '-1'
        with self.assertRaises(ValueError): validate(values, TODAY)

    def test_combined_lump_and_monthly_income_and_shortfall_labels(self):
        values = inputs(); values.update(mode='lump_income', lump_sum='10000')
        result = build(projection(), values, TODAY)
        self.assertEqual(result['payday_cash'], D('16500'))
        baseline = build(projection(), dict(values, lump_sum='0'), TODAY)
        self.assertEqual(result['forecast']['end_cash'] - baseline['forecast']['end_cash'], D('10000'))
        self.assertEqual(result['inputs']['existing'], D(0))
        values.update(mode='lump', lump_sum='0', months='12')
        text = receipt(build(projection(), values, TODAY), TODAY)
        self.assertIn('Funding shortfall at forecast end', text)
        self.assertIn('6 month(s): funding shortfall', text)
        self.assertNotIn('GBP -', text)
        self.assertIn('No savings transfers assumed', text)

    def test_save_all_allocates_only_recurring_surplus_and_updates_forecast(self):
        values = inputs(); values['save_all'] = 'on'
        source = projection()
        result = build(source, values, TODAY)
        self.assertEqual(result['monthly_savings'], D('4240'))
        self.assertEqual(result['spend'], D('200'))
        self.assertIn('Saving all remaining income surplus.', receipt(result, TODAY))
        ordinary = build(source, dict(values, save_all=''), TODAY)
        self.assertEqual(ordinary['forecast']['end_cash']-result['forecast']['end_cash'], D('6480'))
        values.update(mode='lump', lump_sum='10000')
        self.assertEqual(build(source, values, TODAY)['monthly_savings'], D(0))

    def test_additional_income_uses_explicit_existing_salary_once(self):
        values = inputs(); values['mode'] = 'additional'
        result = build(projection(), values, TODAY)
        self.assertEqual(result['payday_cash'], D('8500'))
        self.assertEqual(result['forecast']['payments'][0]['salary'], D('6500'))

    def test_no_income_and_insufficient_cash_report_shortfall(self):
        values = inputs(); values.update(salary='0', other_income='0')
        result = build(projection(), values, TODAY)
        self.assertGreater(result['shortfall'], 0)
        self.assertIsNotNone(result['forecast']['run_out'])
        self.assertEqual(result['savings'], 0)

    def test_invalid_inputs_and_incomplete_sources_are_rejected(self):
        for field, value in [('salary','NaN'), ('salary','-1'), ('start','2026-09-01'), ('months','0'), ('mode','invalid')]:
            values = inputs(); values[field] = value
            with self.assertRaises(ValueError): validate(values, TODAY)
        base = projection(); base['valid'] = False
        with self.assertRaises(ValueError): build(base, inputs(), TODAY)

    def test_future_salary_does_not_hide_shortfall_before_first_payday(self):
        values = inputs(); values['start'] = '2026-11-10'
        result = build(projection(), values, TODAY)
        self.assertLess(result['forecast']['run_out'], date(2026, 11, 10))

    def test_generation_never_prints_and_print_uses_session_owned_saved_test(self):
        app = Flask(__name__); app.secret_key='test'; start=Mock(return_value=(True,''))
        register(app, lambda f:f, start)
        with TemporaryDirectory() as folder, patch('receipt.archive.DIRECTORY', Path(folder)), patch(
            'web_control.test_finance_tools.uk_today', return_value=TODAY), patch(
            'web_control.test_finance_tools.collect', return_value=projection()):
            client=app.test_client()
            response=client.post('/finance/test/generate', data=inputs())
            self.assertEqual(response.status_code, 302)
            start.assert_not_called()
            with client.session_transaction() as session:
                identity=session['test_finance_receipt']
            from receipt.archive import load
            item=load(identity)
            self.assertIn('SIMULATION', item['pages']['finance'])
            response=client.post('/finance/test/print', data={'id':'client-cannot-pick-another-receipt'})
            self.assertEqual(response.status_code,302)
            start.assert_called_once_with(['--archive',identity,'finance'])
            self.assertEqual(client.get('/finance/test/print').status_code,405)

    def test_invalid_generation_does_not_fetch_banks_or_print(self):
        app=Flask(__name__); app.secret_key='test'; start=Mock()
        register(app,lambda f:f,start)
        with patch('web_control.test_finance_tools.collect') as collect, patch(
            'web_control.test_finance_tools.render_template', return_value='error'):
            response=app.test_client().post('/finance/test/generate',data={'salary':'-1'})
        self.assertEqual(response.status_code,400)
        collect.assert_not_called(); start.assert_not_called()

    def test_fully_manual_collection_never_uses_network_or_edits_settings(self):
        from web_control.test_finance_tools import collect
        settings={'hsbc_emergency_reserve':1000}
        original=deepcopy(settings)
        with patch('finance.receipt.load_finance_settings', return_value=settings), patch(
            'services.subscriptions.load_subscriptions', return_value={'monthly':[], 'yearly':[], 'instalments':[]}), patch(
            'finance.rental_tax.protected_reserve',return_value=D(0)), patch(
            'requests.sessions.Session.request') as network:
            base=collect({'opening_cash':'1200','daily_spend':'10'},TODAY)
        self.assertTrue(base['valid'])
        self.assertEqual(base['cash'],D('1200'))
        self.assertEqual(base['buffer'],D('1000'))
        self.assertEqual(settings,original)
        network.assert_not_called()
