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
        self.assertNotIn('GBP 2,000.00', text)
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))

    def test_repayment_options_and_monthly_savings_are_explicit(self):
        source = projection()
        source['repayment_options'] = [{'name': 'Amex', 'balance': '500', 'apr': '24'},
            {'name': 'Roland', 'remaining_balance': '1000', 'amount': '124.92', 'end_date': '2027-06-01'}]
        values = inputs()
        result = build(source, values, TODAY)
        text = receipt(result, TODAY)
        self.assertIn('Potential full payoff', text)
        self.assertIn('Confirm balance/rate', text)
        self.assertIn('Final payment: 01 Jun 2027', text)
        without = dict(values, savings_target='0')
        self.assertEqual(build(source, without, TODAY)['forecast']['end_cash'] - result['forecast']['end_cash'], D('2000'))
        self.assertIn('Savings target not set', receipt(build(source, without, TODAY), TODAY))
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))

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
