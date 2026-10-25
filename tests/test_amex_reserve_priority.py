"""Bills and necessities → Amex → reserve goals → discretionary investments."""
from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.scenario_plan import build
from finance.test_receipt import receipt
from finance.projection import occurs

TODAY = date(2026, 10, 25)
ZERO = D(0)


def base(cash='480', card='1600', daily=None, cash_gap='400', tax='0'):
    gap, tax = D(cash_gap), D(tax)
    physical = D(500) - gap
    return dict(valid=True, cash=D(cash), buffer=D(1000)+gap+tax, daily=daily if daily is not None else D('1705')/31,
                warnings=[], primary_bank='HSBC', monzo_balance=D('2'),
                amex=dict(balance=D(card) if card is not None else None, full_reserved=False, apr=ZERO),
                reserve_details=dict(bank=D(1000), gap=gap, target=D(500), held=physical, tax_reserve=tax, date=TODAY, reserve_label='Tax reserve'),
                events=[dict(name=name, date=occurs(TODAY,m), amount=amount, category=kind)
                        for m in range(12) for name,amount,kind in [('Bills',D('1425'),'bill'),('Amex payment',D(50),'repayment'),('Hargreaves Lansdown',D(25),'savings')]],
                savings_accounts=[dict(id='cash', name='Cash', kind='savings', type='savings', balance=physical,
                                      date=str(TODAY), target=D(500), share=ZERO, isa_contributions=None),
                                  dict(id='isa', name='Hargreaves Lansdown', kind='investment', type='stocks_isa', balance=ZERO,
                                       date=str(TODAY), target=ZERO, share=D(100), isa_contributions=ZERO)])


def values(**changes):
    return dict(dict(salary='3000', other_income='900', start=str(TODAY), months='12', strategy='amex_first',
                     use_saved_accounts='on', invest_spare_cash='on', save_all='on', monzo_target='500'), **changes)


class AmexReservePriorityTests(TestCase):
    def test_low_starting_cash_pays_amex_before_unfilled_targets(self):
        source=base();before=deepcopy(source)
        result=build(source, values(), TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'], D('1175'))
        self.assertEqual(first['savings'], 0)
        self.assertEqual(first['reserve_targets']['cash_transfer'], 0)
        self.assertEqual(first['reserve_targets']['monzo_transfer'], 0)
        self.assertEqual(first['reserve_targets']['hsbc'], 0)
        self.assertEqual(first['costs'], D('1500'))
        self.assertIsNone(result['forecast']['run_out'])
        self.assertEqual(result['shortfall'], 0)
        self.assertEqual(source,before)
        for detail in ('compact','detailed'):
            text=receipt(result,TODAY,detail=detail)
            self.assertIn('Amex - extra repayment',text)
            self.assertIn('£1,175.00',text)
            self.assertIn('necessities',text)
            self.assertNotIn('FUNDING WARNING',text)
            self.assertNotIn('Cash top-up (from reserves)',text)
            self.assertNotIn('Move to Monzo from bank reserves',text)
        for period in result['forecast']['payments']:
            if period['savings']:
                self.assertEqual(period['reserve_targets']['pending'],0)
                self.assertEqual(period['closing_card'],0)
        self.assertEqual(first['automatic_savings'],25)

    def test_700_ceiling_clears_card_and_keeps_remainder_towards_hsbc(self):
        result=build(base(),values(limit_spending_when_owed='on',debt_spending_cap='700'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['variable'],700)
        self.assertTrue(first['spending_limited'])
        self.assertEqual(first['extra'],D('1550'))
        self.assertEqual(first['closing_card'],0)
        self.assertEqual(first['reserve_targets']['hsbc'],D('630'))
        self.assertEqual(first['reserve_targets']['cash_transfer'],0)
        self.assertEqual(first['reserve_targets']['monzo_transfer'],0)
        self.assertEqual(first['savings'],0)
        self.assertIsNone(result['forecast']['run_out'])

    def test_cap_is_a_ceiling_and_normal_budget_returns_after_debt_clears(self):
        source=base(cash='6000',card='100',cash_gap='0',daily=D(40));source['events']=[]
        result=build(source,values(salary='3000',other_income='0',months='2',limit_spending_when_owed='on',debt_spending_cap='700'),TODAY)
        first,second=result['forecast']['payments']
        self.assertEqual(first['variable'],700)
        self.assertEqual(second['variable'],40*(occurs(TODAY,2)-occurs(TODAY,1)).days)
        self.assertFalse(second['spending_limited'])
        source['daily']=D(5)
        lower=build(source,values(months='1',limit_spending_when_owed='on'),TODAY)
        self.assertEqual(lower['forecast']['payments'][0]['variable'],155)

    def test_overdraft_and_projected_overspend_activate_the_ceiling(self):
        source=base(cash='1000',card='0',cash_gap='0',daily=D(50));source['events']=[]
        source['bank_balance_sources']={'HSBC':{'available':D(1200)},'MONZO':{'available':D(-200)}}
        result=build(source,values(salary='3000',other_income='0',months='1',limit_spending_when_owed='on'),TODAY)
        self.assertEqual(result['forecast']['payments'][0]['variable'],700)
        source.pop('bank_balance_sources')
        result=build(source,values(salary='0',other_income='0',months='1',limit_spending_when_owed='on'),TODAY)
        self.assertEqual(result['forecast']['payments'][0]['variable'],700)
        self.assertIsNone(result['forecast']['run_out'])

    def test_partial_cash_topup_credited_only_when_funded_after_bank_targets(self):
        source=base(cash='0',card='0',daily=ZERO)
        source['monzo_balance']=ZERO
        source['events']=[dict(name='Bills',date=occurs(TODAY,m),amount=D(500)) for m in range(12)]
        result=build(source,values(salary='2300',other_income='0',months='2'),TODAY)
        first,second=result['forecast']['payments']
        self.assertEqual(first['reserve_targets']['cash_transfer'],300)
        self.assertEqual(first['reserve_targets']['cash_pending'],D('100'))
        self.assertEqual(first['reserve_targets']['hsbc'],1000)
        self.assertEqual(first['reserve_targets']['monzo_transfer'],500)
        self.assertEqual(first['savings'],0)
        self.assertEqual(second['reserve_targets']['cash_transfer'],D('100'))
        self.assertGreater(second['savings'],0)
        row=next(r for r in result['account_plan']['accounts'] if r['id']=='cash')
        self.assertEqual(row['projected'],500)
        self.assertEqual(row['goal_date'],occurs(TODAY,1))
        self.assertEqual(result['forecast']['reserved_total'],D('400'))
        self.assertEqual(result['forecast']['end_cash']+result['projection']['buffer']-result['forecast']['reserved_total'],1500)

    def test_tax_money_remains_protected_while_bank_goal_waits(self):
        source=base(cash='1000',card='2000',daily=ZERO,tax='400')
        source['events']=[dict(name='Bills',date=TODAY,amount=D(200))]
        result=build(source,values(salary='600',other_income='0',months='1'),TODAY)
        self.assertEqual(result['forecast']['payments'][0]['extra'],1000)
        self.assertEqual(result['forecast']['minimum_bank'],400)
        self.assertIsNone(result['forecast']['run_out'])
        self.assertEqual(result['forecast']['reserved_total'],0)

    def test_no_salary_can_repay_card_but_cannot_sweep_spare_cash_to_investments(self):
        source=base(cash='300',card='500',daily=ZERO,cash_gap='0')
        source['events']=[dict(name='Bills',date=TODAY,amount=D(200))]
        result=build(source,values(salary='0',other_income='900',months='1'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['extra'],500)
        self.assertEqual(first['savings'],0)
        self.assertEqual(first['cash_invested'],0)
        self.assertEqual(first['reserve_targets']['hsbc'],500)

    def test_unknown_card_balance_withholds_discretionary_moves(self):
        source=base(cash='5000',card=None,daily=ZERO)
        source['events']=[]
        result=build(source,values(months='1'),TODAY)
        first=result['forecast']['payments'][0]
        self.assertEqual(first['savings'],0)
        self.assertEqual(first['reserve_targets']['cash_transfer'],0)
        self.assertEqual(first['reserve_targets']['monzo_transfer'],0)
        self.assertIn('Amex balance unknown',receipt(result,TODAY,detail='compact'))

    def test_essentials_shortfall_is_distinct_from_a_target_gap(self):
        source=base(cash='100',card='500',daily=D(10))
        source['events']=[dict(name='Bills',date=TODAY,amount=D(500))]
        result=build(source,values(salary='100',other_income='0',months='1'),TODAY)
        self.assertEqual(result['forecast']['payments'][0]['extra'],0)
        self.assertIsNotNone(result['forecast']['run_out'])
        self.assertGreater(result['shortfall'],0)
        self.assertIn('FUNDING WARNING',receipt(result,TODAY,detail='compact'))

    def test_funded_transfer_instructions_follow_the_allocation_order(self):
        result=build(base(cash='6000',card='100',daily=ZERO),values(months='1'),TODAY)
        for detail in ('compact','detailed'):
            text=receipt(result,TODAY,detail=detail)
            self.assertLess(text.index('Amex - extra repayment'),text.index('Cash top-up funded this period'))
            self.assertLess(text.index('Cash top-up funded this period'),text.index('Hargreaves Lansdown'))

    def test_spending_ceiling_is_saved_and_validated(self):
        from finance.scenario_presets import inputs as saved_inputs
        from finance.scenario_inputs import validate
        form=values(limit_spending_when_owed='on',debt_spending_cap='700')
        saved=saved_inputs(form)
        self.assertEqual(saved['limit_spending_when_owed'],'on')
        self.assertEqual(saved['debt_spending_cap'],'700')
        for invalid in ('NaN','-1','0','100001'):
            with self.assertRaises(ValueError):
                validate(dict(form,debt_spending_cap=invalid),TODAY)

    def test_spending_and_bank_balances_conserve_money_through_partial_topups(self):
        source=base()
        result=build(source,values(),TODAY);f=result['forecast']
        total_income=sum((p['salary']+p['rent'] for p in f['payments']),ZERO)
        costs=sum((e['amount'] for e in f['events']),ZERO)
        days=(f['end']-TODAY).days+1
        bank=f['end_cash']+result['projection']['buffer']-f['reserved_total']
        expected=source['cash']+total_income-costs-source['daily']*days-f['extra_total']-f['savings_total']-f['reserved_total']-f['early_payoff_total']
        self.assertAlmostEqual(bank,expected,places=8)
        self.assertGreaterEqual(f['minimum_bank'],0)
