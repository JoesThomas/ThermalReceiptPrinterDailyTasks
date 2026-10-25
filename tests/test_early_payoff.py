"""Cash conservation, reserve protection and isolated instalment settlement forecasts."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from finance.early_payoff import options
from finance.scenario_plan import build
from finance.test_receipt import receipt
from finance.projection import occurs
from receipt.profile import COLUMNS

TODAY = date(2026, 10, 25)


def source(balance='200', payment='50', name='Amazon headphones'):
    row = dict(name=name, balance=balance, monthly_payment=payment,
               next_payment='2026-11-01', type='payment_plan')
    return dict(valid=True, cash=D(1000), buffer=D(1000), daily=D(0), warnings=[],
                events=[dict(name=name, date=occurs(date(2026, 11, 1), m), amount=D(payment), category='repayment') for m in range(12)],
                repayment_options=[row], amex=dict(balance=D(0), full_reserved=False, apr=D(0)), savings_accounts=[])


def values(base, **changes):
    identifier = options(base['repayment_options'])[0]['id']
    return dict({'salary': '300', 'start': str(TODAY), 'months': '3', 'strategy': 'amex_first',
                 'save_all': 'on', 'early_payoff': 'on', 'payoff_plan_' + identifier: 'on'}, **changes)


class EarlyPayoffTests(TestCase):
    def test_settlement_replaces_scheduled_payment_once_and_frees_later_income(self):
        base = source()
        before = deepcopy(base)
        result = build(base, values(base), TODAY)
        forecast = result['forecast']
        first = forecast['payments'][0]
        self.assertEqual(first['instalment_settled'], 200)
        self.assertEqual(first['instalment_replaced'], 50)
        self.assertEqual(first['instalment_extra'], 150)
        self.assertEqual(first['costs'], 0)
        self.assertEqual(first['savings'], 100)
        self.assertEqual([p['savings'] for p in forecast['payments']], [100, 300, 300])
        self.assertFalse(any(e['name'] == 'Amazon headphones' for e in forecast['events']))
        self.assertEqual(forecast['instalment_balances'][0]['remaining'], 0)
        self.assertEqual(forecast['end_cash'], 0)
        self.assertEqual(base, before)
        for detail in ('compact', 'detailed'):
            text = receipt(result, TODAY, detail=detail)
            self.assertIn('EARLY INSTALMENT PAYOFFS', text)
            self.assertTrue(all(len(line) <= COLUMNS for line in text.splitlines()))
            self.assertIn('£200.00', text)

    def test_disabled_feature_preserves_original_payments(self):
        base = source()
        result = build(base, values(base, early_payoff=''), TODAY)
        self.assertFalse(result['forecast']['early_payoffs'])
        self.assertEqual(sum(e['amount'] for e in result['forecast']['events']), 150)
        self.assertNotIn('EARLY INSTALMENT PAYOFFS', receipt(result, TODAY))

    def test_insufficient_allocation_retains_payments_and_can_settle_later(self):
        base = source('150')
        result = build(base, values(base, salary='100'), TODAY)
        first, second = result['forecast']['payments'][:2]
        self.assertEqual(first['instalment_settled'], 0)
        self.assertEqual(first['costs'], 50)
        self.assertEqual(second['instalment_settled'], 100)
        self.assertEqual(result['forecast']['early_payoffs'][0]['date'], occurs(TODAY, 1))

    def test_amex_first_precedes_instalments_and_savings(self):
        base = source('200')
        base['amex']['balance'] = D(300)
        result = build(base, values(base), TODAY)
        self.assertEqual(result['forecast']['payments'][0]['extra'], 250)
        self.assertEqual(result['forecast']['payments'][0]['instalment_settled'], 0)
        self.assertEqual(result['forecast']['early_payoffs'][0]['date'], occurs(TODAY, 1))

    def test_other_income_can_fund_but_no_salary_does_not_enable_spare_cash(self):
        base = source()
        base['cash'] = D(3000)
        result = build(base, values(base, salary='0', other_income='300', invest_spare_cash='on'), TODAY)
        first = result['forecast']['payments'][0]
        self.assertEqual(first['instalment_settled'], 200)
        self.assertEqual(first['instalment_cash'], 0)
        self.assertEqual(first['cash_invested'], 0)
        none = build(base, values(base, salary='0', invest_spare_cash='on'), TODAY)
        self.assertEqual(none['forecast']['early_payoff_total'], 0)

    def test_future_shortfall_withholds_settlements(self):
        base = source()
        base['events'].append(dict(name='Annual insurance', date=date(2026, 12, 1), amount=D(500)))
        result = build(base, values(base), TODAY)
        self.assertEqual(result['forecast']['early_payoff_total'], 0)
        self.assertIn('withheld', result['forecast']['early_payoff_warning'])

    def test_pre_payday_payment_reduces_settlement_balance(self):
        base = source()
        base['cash'] = D(1050)
        base['events'][0]['date'] = TODAY
        start = TODAY + timedelta(days=1)
        result = build(base, values(base, start=str(start)), TODAY)
        self.assertEqual(result['forecast']['early_payoffs'][0]['amount'], 150)
        self.assertEqual(sum(e['amount'] for e in result['forecast']['events'] if e['name'] == 'Amazon headphones'), 50)

    def test_only_confirmed_known_plans_and_unique_schedules(self):
        base = source()
        unknown = deepcopy(base['repayment_options'][0]); unknown.pop('balance')
        card = dict(base['repayment_options'][0], type='credit_card')
        self.assertEqual(options([unknown, card]), [])
        with self.assertRaisesRegex(ValueError, 'Select at least one'):
            build(base, dict(salary='300', start=str(TODAY), early_payoff='on'), TODAY)
        old = values(base)
        base['repayment_options'][0]['balance'] = '199'
        with self.assertRaisesRegex(ValueError, 'changed'):
            build(base, old, TODAY)
        base = source()
        base['repayment_options'].append(dict(base['repayment_options'][0], name='Other headphones', monthly_commitment_name='Amazon headphones'))
        with self.assertRaisesRegex(ValueError, 'unique'):
            build(base, values(base), TODAY)

    def test_smallest_affordable_balance_first_and_conservation_for_all_strategies(self):
        for strategy in ('amex_first', 'split', 'savings_first'):
            base = source('300')
            small = source('100', '20', 'Amazon kettle')
            base['events'] += small['events']
            base['repayment_options'] += small['repayment_options']
            base['cash'] = D(1200)
            base['amex']['balance'] = D(150)
            form = values(base, salary='600', strategy=strategy, invest_spare_cash='on')
            form['payoff_plan_' + options(base['repayment_options'])[1]['id']] = 'on'
            result = build(base, form, TODAY)
            f = result['forecast']
            self.assertEqual(f['early_payoffs'][0]['name'], 'Amazon kettle')
            self.assertEqual(f['early_payoff_total'], 400)
            self.assertIsNone(f['run_out'])
            self.assertEqual(f['end_cash'], D(200) + D(1800) - sum(e['amount'] for e in f['events']) - f['early_payoff_total'] - f['extra_total'] - f['savings_total'])
            for period in f['payments']:
                self.assertLessEqual(period['extra'] + period['savings'] + period['instalment_extra'], period['budget'])
                self.assertEqual(period['instalment_cash'] + period['cash_repaid'] + period['cash_invested'], max(D(0), period['extra'] + period['savings'] + period['instalment_extra'] - period['income_budget']))

    def test_manual_collection_deduplicates_amazon_alias_and_finishes_live_schedule(self):
        from web_control.test_finance_tools import collect
        raw = source()['repayment_options'][0]
        alias = dict(name='Amazon Monthly Payments', balance='200', monthly_payment='50', type='payment_plan')
        local = dict(settings=dict(debts=[alias], emergency_buffer='1000'),
                     subscriptions=dict(monthly=[], yearly=[], instalments=[raw]), accounts=[])
        form = dict(salary='300', start=str(TODAY), months='3', opening_cash='1000', daily_spend='0', amex_owed='0', save_all='on')
        with patch('finance.annual_funds.protected_reserve', return_value=D(0)), patch('finance.amex_protection.assess', return_value=dict(enabled=False, valid=True, statement=None, warnings=[])):
            base = collect(form, TODAY, local=local)
        self.assertTrue(base['valid'])
        choices = options(base['repayment_options'])
        self.assertEqual([r['name'] for r in choices], ['Amazon headphones'])
        form.update(early_payoff='on', **{'payoff_plan_' + choices[0]['id']: 'on'})
        result = build(base, form, TODAY)
        self.assertEqual(result['forecast']['early_payoff_total'], 200)
        self.assertEqual(result['forecast']['instalment_balances'][0]['remaining'], 0)
        self.assertEqual(local['subscriptions']['instalments'][0]['balance'], '200')

    def test_named_scenario_roundtrip_and_old_scenarios_remain_valid(self):
        from finance import scenario_presets
        base = source()
        with TemporaryDirectory() as directory, patch.object(scenario_presets, 'FILE', Path(directory)/'scenarios.json'):
            identifier = scenario_presets.save('Pay off plans', values(base), TODAY)
            saved = scenario_presets.load(identifier)['values']
            self.assertEqual(saved['early_payoff'], 'on')
            self.assertEqual(build(base, saved, TODAY)['forecast']['early_payoff_total'], 200)
            old = dict(saved); old.pop('early_payoff')
            for key in list(old):
                if key.startswith('payoff_plan_'): old.pop(key)
            scenario_presets.validate_inputs(old, TODAY)
