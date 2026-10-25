"""Protected cash floors and calendar-end balances use actual dated allocations."""
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from test_amex_reserve_priority import base, values, TODAY, ZERO
from finance.scenario_plan import build
from finance.scenario_inputs import validate
from finance.scenario_presets import inputs as saved_inputs
from finance.test_receipt import receipt
from finance.test_scenarios import snapshot


class MinimumBankTests(TestCase):
    def test_editable_floor_limits_extra_amex_and_is_part_of_hsbc_target(self):
        for minimum,extra in [('500','675'),('750','425'),('0','1175')]:
            result=build(base(),values(months='1',minimum_bank_balance=minimum),TODAY)
            f=result['forecast']; first=f['payments'][0]
            self.assertEqual(first['extra'],D(extra))
            self.assertAlmostEqual(f['minimum_bank'],D(minimum),places=8)
            self.assertEqual(first['reserve_targets']['hsbc'],D(minimum))
            self.assertEqual(first['savings'],0)
            self.assertIsNone(f['run_out'])
            self.assertEqual(result['projection']['buffer'],1900)
        for detail in ('compact','detailed'):
            text=receipt(build(base(),values(months='1',minimum_bank_balance='500'),TODAY),TODAY,detail=detail)
            self.assertIn('Minimum bank balance to keep',text)
            self.assertIn('Lowest projected bank balance',text)

    def test_tax_earmarks_remain_additional_and_essential_shortfalls_are_real(self):
        result=build(base(tax='400'),values(months='1',minimum_bank_balance='500'),TODAY)
        self.assertAlmostEqual(result['forecast']['minimum_bank'],900,places=8)
        source=base(cash='100',card='500',daily=D(10));source['monzo_balance']=ZERO
        source['events']=[dict(name='Bills',date=TODAY,amount=D(500))]
        result=build(source,values(salary='100',other_income='0',months='1',minimum_bank_balance='500'),TODAY)
        self.assertEqual(result['forecast']['payments'][0]['extra'],0)
        self.assertLess(result['forecast']['minimum_bank'],500)
        self.assertIsNotNone(result['forecast']['run_out'])

    def test_minimum_also_blocks_unaffordable_early_settlement(self):
        from test_early_payoff import source, values as payoff_values
        data=source();data['cash']=ZERO
        result=build(data,payoff_values(data,salary='600',months='1',minimum_bank_balance='500'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['instalment_settled'],0)
        self.assertEqual(first['savings'],0)
        self.assertEqual(result['forecast']['minimum_bank'],550)

    def test_setting_validation_and_named_scenario_roundtrip(self):
        form=values(minimum_bank_balance='650.25')
        self.assertEqual(saved_inputs(form)['minimum_bank_balance'],'650.25')
        self.assertEqual(validate(form,TODAY)['minimum_bank_balance'],D('650.25'))
        for invalid in ('','-1','NaN','Infinity','10000001'):
            with self.assertRaises(ValueError):
                validate(values(minimum_bank_balance=invalid),TODAY)


class CalendarMonthBalanceTests(TestCase):
    def test_month_end_is_calendar_date_and_does_not_include_next_payday(self):
        source=base()
        result=build(source,values(months='2',minimum_bank_balance='500'),TODAY)
        f=result['forecast']; months=f['monthly_balances']
        self.assertEqual([m['date'] for m in months],[date(2026,10,31),date(2026,11,30)])
        first=months[0]; accounts={a['name']:a['balance'] for a in first['accounts']}
        period=f['payments'][0]
        expected=source['cash']+period['salary']+period['rent']-sum(e['amount'] for e in f['events'] if e['date']<=first['date'])-source['daily']*7-period['extra']-period['savings']
        self.assertAlmostEqual(accounts['HSBC']+accounts['Monzo'],expected,places=2)
        self.assertEqual(accounts['Amex - balance owed'],D(1600)-period['extra']-50)
        for detail in ('compact','detailed'):
            text=receipt(result,TODAY,detail=detail)
            self.assertIn('BALANCES AT OCTOBER 2026 END',text)
            self.assertIn('BALANCES AT NOVEMBER 2026 END',text)
        self.assertEqual(snapshot(result,TODAY)['monthly_balances'][0]['date'],'2026-10-31')

    def test_month_end_savings_include_interest_and_match_final_snapshot(self):
        source=base(card='0',daily=ZERO)
        source['savings_accounts'][1].update(type='savings',interest_rate=D('3.5'))
        form=values(start='2026-11-01',months='1',minimum_bank_balance='500')
        result=build(source,form,TODAY)
        f=result['forecast']; month=f['monthly_balances'][0]
        self.assertEqual(month['date'],f['end'])
        balances={a['name']:a['balance'] for a in month['accounts']}
        for account in result['account_plan']['accounts']:
            self.assertEqual(balances[account['name']],account['projected'])
        bank=balances['HSBC']+balances['Monzo']
        self.assertAlmostEqual(bank,f['end_cash']+result['projection']['buffer']-f['reserved_total'],places=2)
        self.assertGreater(f['savings_interest'],0)
