from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from flask import Flask
from finance.test_receipt import build, receipt, validate
from finance.test_scenarios import compare
from receipt import archive
from web_control.test_finance_tools import register

TODAY=date(2026,10,11)


def source():
    return {'valid':True,'cash':D(3000),'buffer':D(1000),'daily':D(10),'warnings':[],
            'events':[],'amex':{'balance':D(1000),'full_reserved':False,'apr':D(0)},
            'savings_accounts':[{'id':'isa','name':'ISA','kind':'investment','type':'stocks_isa','balance':D(0),
                                'date':str(TODAY),'target':D(3000),'share':D(100),'isa_contributions':D(0)}]}


def values(**changes):
    return dict({'salary':'1000','start':str(TODAY),'months':'3','save_all':'on','strategy':'amex_first',
                 'invest_spare_cash':'on','use_saved_accounts':'on'},**changes)


class ForecastScenariosTests(TestCase):
    def test_salary_window_and_other_income(self):
        result=build(source(),values(salary_start='2026-11-01',salary_end='2026-11-30',other_income='100'),TODAY)
        periods=result['forecast']['payments']
        self.assertEqual([p['salary'] for p in periods],[0,1000,0])
        self.assertEqual([p['rent'] for p in periods],[100]*3)
        self.assertEqual(periods[0]['cash_invested'],0)
        self.assertEqual(periods[2]['cash_invested'],0)
        self.assertEqual(periods[0]['cash_repaid'],0)

    def test_one_missed_salary_pauses_spare_cash(self):
        result=build(source(),values(missed_salary_dates='2026-11-11'),TODAY)
        self.assertEqual([p['salary'] for p in result['forecast']['payments']],[1000,0,1000])
        self.assertEqual(result['forecast']['payments'][1]['cash_invested'],0)

    def test_one_off_cost_occurs_once_and_reduces_available_allocation(self):
        base=source();before=deepcopy(base)
        baseline=build(base,values(),TODAY)
        result=build(base,values(one_off_expenses='2026-10-20 | 300 | Holiday'),TODAY)
        self.assertEqual(sum(e['amount'] for e in result['forecast']['events'] if e.get('scenario_expense')),300)
        self.assertEqual(baseline['forecast']['savings_end']-result['forecast']['savings_end'],300)
        self.assertEqual(base,before)

    def test_expense_named_after_card_is_not_a_repayment_or_savings_credit(self):
        result=build(source(),values(salary='0',one_off_expenses='2026-10-20 | 300 | Amex holiday'),TODAY)
        self.assertEqual(result['forecast']['card_end'],1000)
        self.assertEqual(result['forecast']['payments'][0]['costs'],300)
        base=source();base['savings_accounts'][0]['name']='Hargreaves Lansdown'
        hl=build(base,values(one_off_expenses='2026-10-20 | 30 | Hargreaves Lansdown'),TODAY)
        self.assertEqual(hl['forecast']['automatic_total'],0)

    def test_invalid_dates_and_expenses(self):
        for settings in [values(salary_start='bad'),values(salary_start='2026-12-01',salary_end='2026-11-01'),
                         values(missed_salary_dates='2026-11-12'),values(comparison_spend='-1'),
                         values(one_off_expenses='2026-10-01 | 10 | Past'),values(one_off_expenses='2027-02-01 | 10 | Outside'),
                         values(one_off_expenses='2026-10-20 | -10 | Negative'),values(one_off_expenses='wrong format')]:
            with self.assertRaises(ValueError): validate(settings,TODAY)

    def test_spending_changes_are_monthly_not_daily_and_stop_at_zero(self):
        normal=build(source(),values(),TODAY)
        lower=build(source(),values(),TODAY,spending_adjustment=D(-100))
        self.assertEqual(sum(p['variable'] for p in normal['forecast']['payments'])-sum(p['variable'] for p in lower['forecast']['payments']),D(300))
        floor=build(source(),values(),TODAY,spending_adjustment=D(-10000))
        self.assertEqual(sum(p['variable'] for p in floor['forecast']['payments']),0)
        self.assertIsNone(lower['forecast']['run_out'])

    def test_comparisons_use_same_snapshot_and_retain_exact_goal_dates(self):
        base=source();before=deepcopy(base)
        result=build(base,values(),TODAY)
        details=compare(base,values(),TODAY,current=result)
        self.assertEqual([r['name'] for r in details['scenarios']],['Lower spending','Current plan','Higher spending'])
        self.assertEqual(base,before)
        self.assertEqual(details['scenarios'][1]['savings_end'],f"£{result['forecast']['savings_end']:,.2f}")
        self.assertEqual(details['scenarios'][1]['accounts'][0]['goal_date'],(result['account_plan']['accounts'][0]['goal_date'] or result['account_plan']['accounts'][0].get('extended_goal_date')).isoformat())
        self.assertEqual(details['sensitivity']['savings_change'],'£300.00')
        result['sensitivity']=details['sensitivity']
        text=receipt(result,TODAY)
        self.assertIn('Lowest projected bank balance',text)
        self.assertNotIn('month(s): cash above reserves',text)
        self.assertIn('Rough planning estimate',' '.join(text.split()))
        self.assertIn('Projected target date: around',' '.join(text.split()))
        self.assertTrue(all(len(line)<=42 for line in text.splitlines()))

    def test_minimum_bank_balance_tracks_daily_costs_and_reserve_transfers(self):
        result=build(source(),values(),TODAY)
        self.assertAlmostEqual(result['forecast']['minimum_bank'],D(1000),places=2)
        base=source();base.update(cash=D(1000),buffer=D(1280),daily=D(0),amex=None)
        base['reserve_details']={'gap':D(280),'tax_reserve':D(0),'held':D(220),'target':D(500),'date':TODAY}
        base['savings_accounts']=[dict(base['savings_accounts'][0],id='cash',name='Cash',kind='savings',type='savings',balance=D(220),target=D(500))]
        result=build(base,values(),TODAY)
        self.assertEqual(result['forecast']['reserved_total'],280)
        self.assertEqual(result['forecast']['minimum_bank'],1000)

    def test_details_are_saved_with_receipt_and_survive_reload_without_bank_calls(self):
        app=Flask(__name__);app.secret_key='test';register(app,lambda f:f,Mock())
        with TemporaryDirectory() as folder,patch.object(archive,'DIRECTORY',Path(folder)),patch('web_control.test_finance_tools.collect',return_value=source()) as collect,patch('web_control.test_finance_tools.uk_today',return_value=TODAY),patch('finance.receipt.load_finance_settings',return_value={}),patch('web_control.test_finance_tools.render_template',return_value='ok') as render:
            client=app.test_client()
            response=client.post('/finance/test/generate',data=values(one_off_expenses='2026-10-20 | 10 | Test',csrf_token='do-not-store'))
            self.assertEqual(response.status_code,302)
            with client.session_transaction() as session: identifier=session['test_finance_receipt']
            item=archive.load(identifier)
            self.assertNotIn('csrf_token',item['test_finance']['values'])
            client.get('/finance/test')
            self.assertEqual(collect.call_count,1)
            self.assertEqual(len(render.call_args.kwargs['scenario_details']['scenarios']),3)
            self.assertEqual(render.call_args.kwargs['values']['one_off_expenses'],'2026-10-20 | 10 | Test')

    def test_salary_end_prevents_a_misleading_extended_goal_date(self):
        base=source();base['savings_accounts'][0]['target']=D(10000)
        result=build(base,values(salary_end='2026-10-31'),TODAY)
        self.assertIsNone(result['account_plan']['accounts'][0]['goal_date'])
        self.assertIsNone(result['account_plan']['accounts'][0]['extended_goal_date'])
        self.assertTrue(all(p['salary']==0 for p in result['forecast']['payments'][1:]))

    def test_spending_comparison_at_zero_does_not_invent_savings(self):
        base=source();base['daily']=D(0)
        details=compare(base,values(),TODAY)
        self.assertEqual(details['sensitivity']['savings_change'],'£0.00')
        self.assertEqual(details['scenarios'][0]['savings_end'],details['scenarios'][1]['savings_end'])
