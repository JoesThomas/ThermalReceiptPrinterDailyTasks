from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from finance import amex_protection as amex
from storage import write_json

TODAY = date(2026, 10, 22)


def config(**changes):
    value = amex.defaults()
    value.update(enabled=True, source='manual', dd_mode='none',
                 manual_statement={'date': '2026-10-01', 'due': '2026-10-28', 'balance': '500.00'},
                 evidence={'checked_at': '2026-10-22T08:00:00+00:00', 'balances': {'HSBC': '3000.00', 'MONZO': '0.00'},
                           'amex_ok': True, 'card_key': amex.card_key('card1'), 'current': '750.00',
                           'minimum': '25.00', 'from': '2026-09-01', 'payments': [], 'funding_complete': True,
                           'costs': [], 'daily': '0.00', 'buffer': '1000.00'})
    value.update(changes)
    return value


def payment(description='PAYMENT RECEIVED', **changes):
    return {'_source_provider': 'AMEX', '_source_account': 'card1', 'transaction_type': 'CREDIT',
            'description': description, 'amount': -200, 'date': '2026-10-20', 'transaction_id': description, **changes}


class AmexProtectionTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'protection.json'
        self.patcher = patch.object(amex, 'FILE', self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_disabled_until_setup_and_current_balance_is_not_statement(self):
        self.assertFalse(amex.assess(today=TODAY)['enabled'])
        value = config(source='auto')
        result = amex.assess(value, today=TODAY)
        self.assertIsNone(result['statement'])
        self.assertFalse(result['valid'])
        self.assertEqual(result['current'], 750)

    def test_statement_due_date_and_remaining_are_distinct_from_current(self):
        value = config()
        value['evidence']['payments'] = amex.payment_rows([payment(), payment()])
        result = amex.assess(value, today=TODAY)
        self.assertEqual(result['statement']['balance'], 500)
        self.assertEqual(result['confirmed'], 200)
        self.assertEqual(result['remaining'], 300)
        self.assertEqual(result['current'], 750)
        self.assertEqual(result['days'], 6)
        self.assertTrue(any('£300.00' in line and '6 days' in line for line in result['warnings']))

    def test_only_amex_confirmed_payments_count_not_refunds_bank_debits_or_other_cards(self):
        rows = [payment(), payment('REFUND'), payment('PAYMENT RECEIVED REVERSAL'),
                payment(_source_provider='HSBC'), payment(transaction_type='DEBIT'),
                payment(_source_account='card2', transaction_id='other'), payment(date='2026-10-01', transaction_id='old')]
        value = config()
        value['evidence']['payments'] = amex.payment_rows(rows)
        self.assertEqual(amex.assess(value, today=TODAY)['confirmed'], 200)

    def test_manual_confirmation_is_not_added_twice_and_does_not_carry_to_next_statement(self):
        value = config(confirmed_statement='2026-10-01', confirmed_through='2026-10-21', confirmed_total='200.00')
        value['evidence']['payments'] = amex.payment_rows([payment()])
        self.assertEqual(amex.assess(value, today=TODAY)['confirmed'], 200)
        value['manual_statement'] = {'date': '2026-10-21', 'due': '2026-11-15', 'balance': '750.00'}
        self.assertEqual(amex.assess(value, today=TODAY)['confirmed'], 0)

    def test_reminders_on_seven_three_one_days_and_overdue(self):
        for days in (7, 3, 1, 0, -1):
            value = config()
            value['manual_statement']['due'] = (TODAY + timedelta(days=days)).isoformat()
            result = amex.assess(value, today=TODAY)
            self.assertTrue(any('unpaid' in line or 'unconfirmed after' in line for line in result['warnings']))

    def test_full_dd_funded_is_quiet_and_fixed_minimum_warn(self):
        result = amex.assess(config(dd_mode='full'), today=TODAY)
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['confirmed'], 0)
        self.assertEqual(result['scheduled'], 500)
        for changes in ({'dd_mode': 'fixed', 'dd_amount': '50.00'}, {'dd_mode': 'minimum'}):
            result = amex.assess(config(**changes), today=TODAY)
            self.assertTrue(result['warnings'])
            self.assertEqual(result['remaining'], 500)

    def test_bill_reserves_and_payment_account_can_each_cause_shortfall(self):
        value = config(dd_mode='full')
        value['evidence']['balances'] = {'HSBC': '1200.00', 'MONZO': '0.00'}
        value['evidence']['costs'] = [{'date': '2026-10-25', 'amount': '750.00'}]
        result = amex.assess(value, today=TODAY)
        self.assertEqual(result['cash_gap'], 1050)
        value['evidence']['balances'] = {'HSBC': '100.00', 'MONZO': '10000.00'}
        self.assertEqual(amex.assess(value, today=TODAY)['cash_gap'], 400)

    def test_stale_data_and_missing_transaction_window_are_not_safe(self):
        value = config(dd_mode='full')
        value['evidence']['checked_at'] = '2026-10-19T08:00:00+00:00'
        self.assertFalse(amex.assess(value, today=TODAY)['valid'])
        value = config()
        value['evidence']['from'] = '2026-10-10'
        self.assertFalse(amex.assess(value, today=TODAY)['valid'])

    def test_residual_interest_and_manual_payment_dd_overlap(self):
        value = config(dd_mode='full', carried_balance='yes', confirmed_statement='2026-10-01', confirmed_through='2026-10-21', confirmed_total='500.00')
        result = amex.assess(value, today=TODAY)
        self.assertEqual(result['remaining'], 0)
        self.assertEqual(result['reserve'], 500)
        self.assertFalse(result['valid'])
        self.assertTrue(any('residual' in line for line in result['warnings']))
        self.assertIn('four working days', result['dd_caution'])

    def test_projection_replaces_current_50_only_once_and_salary_protects_future_due(self):
        from finance.projection import build_projection
        from finance.salary_plan import build
        write_json(self.path, config())
        balances = {'HSBC': {'available': 2000}, 'MONZO': {'available': 0}, 'AMEX': {'current': 750}}
        settings = {'hsbc_emergency_reserve': 1000, 'runway_daily_spend': 0,
                    'next_payday': '2026-10-25', 'salary_savings_target': 1000}
        monthly = [{'name': 'Amex', 'amount': 50, 'due_date': '2026-10-25'}]
        projection = build_projection(balances, [], monthly, [], settings, TODAY, horizon=65)
        current = [row for row in projection['events'] if row['date'] <= date(2026, 10, 28)]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['amount'], 500)
        self.assertTrue(any(row['amount'] == 50 and row['date'].month == 11 for row in projection['events']))
        result = build([{'date': TODAY, 'amount': 2000}], [], balances, projection, settings, None, TODAY)
        self.assertEqual(result['bills_cost'], 500)
        self.assertEqual(result['buckets'][2]['amount'], 500)

    def test_future_protected_statement_cannot_be_invested_in_first_test_period(self):
        from finance.test_receipt import build
        base = {'valid': True, 'cash': D(3000), 'buffer': D(1000), 'daily': D(0), 'warnings': [],
                'events': [{'name': 'Amex statement repayment', 'date': date(2026, 12, 1), 'amount': D(500), 'amex_statement_protection': True}],
                'amex': {'balance': D(500), 'apr': D(0)}}
        values = {'salary': '100', 'start': str(TODAY), 'months': '2', 'savings_target': '0', 'invest_spare_cash': 'on', 'strategy': 'savings_first'}
        result = build(base, values, TODAY)
        first = result['forecast']['payments'][0]
        self.assertLessEqual(first['savings'], 1600)
        self.assertEqual(result['forecast']['card_end'], 0)
        self.assertIsNone(result['forecast']['run_out'])

    def test_statement_reserve_above_current_balance_cannot_be_released_to_savings(self):
        value = config(dd_mode='full')
        value['evidence']['current'] = '100.00'
        result = amex.assess(value, today=TODAY)
        self.assertFalse(result['valid'])
        self.assertEqual(result['reserve'], 500)
        self.assertTrue(any('exceeds' in line for line in result['warnings']))

    def test_daily_output_quiet_when_covered_finance_has_breakdown(self):
        rows = []
        printer = Mock()
        result = amex.assess(config(dd_mode='full'), today=TODAY)
        amex.print_status(printer, lambda _, text: rows.append(text), lambda *_: None, result)
        self.assertEqual(rows, [])
        amex.print_status(printer, lambda _, text: rows.append(text), lambda *_: None, result, detailed=True)
        self.assertTrue(any('Statement balance: £500.00' in row for row in rows))
        self.assertTrue(any('Confirmed repayments: £0.00' in row for row in rows))

    def test_failed_refresh_keeps_confirmation_but_invalidates_safety_status(self):
        value = config(dd_mode='full')
        value['evidence']['payments'] = amex.payment_rows([payment()])
        write_json(self.path, value)
        amex.mark_failed()
        result = amex.assess(today=TODAY)
        self.assertEqual(result['confirmed'], 200)
        self.assertFalse(result['valid'])
        self.assertTrue(any('stale' in line for line in result['warnings']))

    def test_backup_round_trip_and_invalid_settings(self):
        import json
        from web_control.private_backup import export, validate, restore
        root = Path(self.folder.name)
        write_json(root / 'data' / 'amex_payment_protection.json', config())
        backup = validate(export(root))
        with TemporaryDirectory() as other:
            restore(Path(other), backup)
            self.assertTrue(amex.store(Path(other) / 'data' / 'amex_payment_protection.json').read()['enabled'])
        backup['files']['amex_payment_protection.json']['dd_amount'] = 'NaN'
        with self.assertRaises(ValueError):
            validate(json.dumps(backup).encode())

    def test_auto_bank_statement_fields_are_retained(self):
        from finance import bank_accounts
        with patch.object(bank_accounts, 'selection', return_value={}), patch.object(bank_accounts, 'CATALOG', Path(self.folder.name) / 'catalog.json'), patch('finance.bank_overdrafts.load', return_value={}):
            def get(token, resource):
                if resource == '/accounts':
                    return {'results': [{'account_id': token}]}
                if resource == '/cards':
                    return {'results': [{'account_id': 'card1'}]}
                if resource.endswith('/balance'):
                    return {'results': [{'current': 1000, 'available': 1000, 'last_statement_balance': 500,
                                         'last_statement_date': '2026-10-01', 'payment_due_date': '2026-10-28', 'payment_due': 25}]}
            balances = bank_accounts.collect(lambda p, _: p, lambda p: p, get)
            self.assertEqual(balances['AMEX']['last_statement_balance'], 500)
            self.assertEqual(balances['AMEX']['payment_due'], 25)
            self.assertEqual(balances['AMEX']['statement_card_key'], amex.card_key('card1'))

    def test_form_validation_is_atomic_and_saves_real_payment_arrangement(self):
        from flask import Flask
        from web_control.amex_protection import register
        app = Flask(__name__)
        app.secret_key = 'test'
        app.add_url_rule('/finance-review', endpoint='finance_review', view_func=lambda: 'review')
        register(app, lambda fn: fn)
        form = {'enabled': 'on', 'source': 'manual', 'statement_date': '2026-10-01',
                'statement_balance': '500', 'due_date': '2026-10-28', 'dd_mode': 'fixed',
                'dd_amount': '50', 'paying_account': 'HSBC', 'carried_balance': 'no', 'confirmed_total': '0'}
        with app.test_client() as client, patch.object(amex, 'uk_today', return_value=TODAY):
            response = client.post('/finance/amex-protection', data=form)
            self.assertEqual(response.status_code, 302)
            value = amex.store().read()
            self.assertEqual(value['manual_statement']['balance'], '500.00')
            self.assertEqual(value['dd_amount'], '50.00')
            original = self.path.read_bytes()
            client.post('/finance/amex-protection', data={**form, 'confirmed_total': '1000', 'confirmed_through': '2026-10-22'})
            self.assertEqual(self.path.read_bytes(), original)
            client.post('/finance/amex-protection', data={**form, 'due_date': 'not-a-date'})
            self.assertEqual(self.path.read_bytes(), original)

    def test_capture_uses_bank_statement_and_no_network_funding_calculation(self):
        summary = {'bank_data_status': 'complete', 'requested_from': '2026-09-01',
                   'source_coverage': [{'provider': 'AMEX', 'status': 'Loaded'}]}
        balances = {'HSBC': {'available': 3000}, 'MONZO': {'available': 0},
                    'AMEX': {'current': 750, 'last_statement_balance': 500, 'last_statement_date': '2026-10-01',
                             'payment_due_date': '2026-10-28', 'payment_due': 25, 'statement_card_key': amex.card_key('card1')}}
        write_json(self.path, config(source='auto'))
        import sys
        from types import SimpleNamespace
        pipeline = SimpleNamespace(build_subscription_status=lambda _: {'monthly': [], 'yearly': []})
        with patch.dict(sys.modules, {'services.live_pipeline': pipeline}), patch('finance.receipt.load_finance_settings', return_value={'runway_daily_spend': 0}):
            amex.capture(balances, [payment()], summary, checked_at='2026-10-22T08:00:00+00:00')
        result = amex.assess(today=TODAY)
        self.assertEqual(result['remaining'], 300)
        self.assertEqual(result['statement']['balance'], 500)
        self.assertTrue(result['valid'])
        before = self.path.read_bytes()
        amex.capture({}, [], {'bank_data_status': 'unavailable'})
        self.assertEqual(self.path.read_bytes(), before)
