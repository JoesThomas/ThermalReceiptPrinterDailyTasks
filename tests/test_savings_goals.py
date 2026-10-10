import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from finance import savings_goals as goals
from web_control import private_backup


class SavingsGoalTests(unittest.TestCase):
    def test_tax_year_boundaries(self):
        self.assertEqual(goals.tax_year(date(2026,4,5)),2025)
        self.assertEqual(goals.tax_year(date(2026,4,6)),2026)

    def test_premium_goal_and_custom_target_without_publishing_private_balances(self):
        wealth={'accounts':[{'name':'Premium Bonds','kind':'savings','balance':Decimal(25000),'latest':{'date':'2026-10-04','source':'manual'}},
                            {'name':'Example savings','kind':'savings','balance':Decimal(200),'latest':{'date':'2026-10-04','source':'manual'}}]}
        state={'accounts':{goals.identity('Example savings','savings'):{'name':'Example savings','kind':'savings','type':'savings','target':'400'}},'entries':[],'years':{}}
        view=goals.review(wealth,state=state,on=date(2026,10,4),bond_balances=[])
        self.assertEqual(view['premium']['percent'],50)
        self.assertEqual(view['premium']['remaining'],25000)
        self.assertEqual(next(row for row in view['accounts'] if row['name']=='Example savings')['percent'],50)
        self.assertIn('PREMIUM BONDS BALANCE GOAL', goals.receipt_lines(view))

    def test_premium_bonds_summary_displays_the_named_account_once(self):
        from flask import Flask, render_template
        name='Example premium bonds'
        for target in (None, '50000'):
            state={'accounts':{goals.identity(name,'savings'):{'name':name,'kind':'savings','type':'premium_bonds','target':target}},'entries':[],'years':{}}
            wealth={'accounts':[{'name':name,'kind':'savings','balance':Decimal(25000),'latest':{'date':'2026-10-04','source':'manual'}}]}
            view=goals.review(wealth,state=state,on=date(2026,10,4),bond_balances=[])
            app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'web_control'/'templates'))
            app.add_url_rule('/goals',endpoint='savings_goals_page',view_func=lambda: '')
            with app.test_request_context():
                html=render_template('savings_goal_summary.html',goals=view)
            self.assertNotIn('Premium Bonds holdings',html)
            self.assertEqual(html.count('<article class="goal-card">'),1)
            self.assertIn(name,html)
            self.assertIn('£25,000.00 / £50,000.00',html)
            for balances in (False,True):
                lines=goals.receipt_lines(view,include_balances=balances)
                self.assertNotIn('PREMIUM BONDS HOLDING GOAL',lines)
                self.assertEqual(sum(name.upper() in line for line in lines),1)
                self.assertTrue(all(len(line)<=40 for line in lines))

    def test_premium_bonds_uses_latest_dated_balance_after_withdrawal(self):
        name='Example premium bonds'
        state={'accounts':{goals.identity(name,'savings'):{'name':name,'kind':'savings','type':'premium_bonds','target':'50000'}},'entries':[],'years':{}}
        for source in ('manual','local observation'):
            for account_date,ledger_date,account_balance,ledger_balance in (
                ('2026-10-04','2026-01-01',30000,35000),
                ('2026-01-01','2026-10-04',35000,30000),
                ('2026-01-01','2026-10-04',35000,0),
            ):
                wealth={'accounts':[{'name':name,'kind':'savings','balance':Decimal(account_balance),'latest':{'date':account_date,'source':source}}]}
                bonds=[{'date':ledger_date,'amount':str(ledger_balance)}]
                view=goals.review(wealth,state=state,on=date(2026,10,4),bond_balances=bonds)
                expected=Decimal(account_balance if account_date>ledger_date else ledger_balance)
                row=view['accounts'][0]
                self.assertEqual(row['balance'],expected)
                self.assertEqual(row['balance_date'],max(account_date,ledger_date))
                self.assertEqual(view['premium']['balance'],expected)
                self.assertEqual(row['balance_goal']['remaining'],50000-expected)

    def test_manual_premium_bonds_balance_wins_equal_date_and_future_is_excluded(self):
        wealth={'accounts':[{'name':'Example premium bonds','kind':'savings','balance':Decimal(30000),
                            'latest':{'date':'2026-10-04','source':'manual'}}]}
        state={'accounts':{},'entries':[],'years':{}}
        view=goals.review(wealth,state=state,on=date(2026,10,4),bond_balances=[
            {'date':'2026-10-04','amount':'35000'},{'date':'2026-10-05','amount':'40000'}])
        self.assertEqual(view['accounts'][0]['balance'],30000)

    def test_isa_combined_contributions_reset_growth_and_transfers_excluded(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(goals,'FILE',Path(folder)/'goals.json'),patch.object(goals,'today',return_value=date(2026,10,4)):
            goals.account_settings('Example cash ISA','savings','cash_isa')
            goals.account_settings('Example stocks ISA','investment','stocks_isa')
            cash=goals.identity('Example cash ISA','savings');stocks=goals.identity('Example stocks ISA','investment')
            goals.record(cash,'2026-04-05',1000)
            goals.record(cash,'2026-04-06',3000)
            goals.record(stocks,'2026-06-01',4000)
            for event in ('transfer','withdrawal','replacement','interest'):goals.record(stocks,'2026-07-01',5000,event)
            wealth={'accounts':[{'name':'Example stocks ISA','kind':'investment','balance':Decimal(99999),'latest':{'date':'2026-10-04','source':'manual'}}]}
            view=goals.review(wealth,on=date(2026,10,4),bond_balances=[])
            self.assertEqual(view['shared']['used'],7000)
            self.assertEqual(next(a for a in view['accounts'] if a['id']==stocks)['interest'],5000)
            self.assertIn('RECORDED INTEREST GBP 5000.00',' '.join(goals.receipt_lines(view)))
            self.assertEqual(view['shared']['percent'],35)
            self.assertEqual(view['cash']['used'],3000)
            self.assertFalse(view['shared']['complete'])
            goals.year_settings(2026,20000,20000,True)
            view=goals.review(wealth,on=date(2026,10,4),bond_balances=[])
            self.assertEqual(view['shared']['remaining'],13000)
            self.assertTrue(view['shared']['complete'])
            self.assertEqual(goals.review(wealth,2025,on=date(2026,10,4),bond_balances=[])['shared']['used'],1000)
            first=goals.load()['entries'][1]
            goals.record(cash,'2026-04-06',3500,entry_id=first['id'])
            self.assertFalse(goals.review(on=date(2026,10,4),bond_balances=[])['shared']['complete'])
            self.assertEqual(goals.FILE.stat().st_mode & 0o777,0o600)
            raw=json.dumps({'version':1,'files':{'savings_goals.json':goals.load()}}).encode()
            self.assertIn('savings_goals.json',private_backup.validate(raw)['files'])
            goals.remove(first['id'])
            self.assertNotIn(first['id'],[row['id'] for row in goals.load()['entries']])

    def test_future_cash_limit_unknown_over_limit_clamped_and_history_survives_type_changes(self):
        state={'accounts':{'':{}},'entries':[],'years':{}}
        key=goals.identity('Example ISA','investment')
        state={'accounts':{key:{'name':'Example ISA','kind':'investment','type':'stocks_isa','target':None}},
               'entries':[{'id':'one','account':key,'date':'2027-04-06','amount':'23000','event':'contribution','isa_type':'cash_isa'}],'years':{}}
        view=goals.review(state=state,on=date(2027,5,1),bond_balances=[])
        self.assertEqual(view['shared']['percent'],100)
        self.assertEqual(view['shared']['over'],3000)
        self.assertEqual(view['cash']['used'],23000)
        self.assertIsNone(view['cash']['limit'])
        self.assertIn('VERIFY CASH ISA LIMIT',' '.join(goals.receipt_lines(view)))

    def test_cash_rate_edit_keeps_contributions_and_survives_settings(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(goals,'FILE',Path(folder)/'goals.json'):
            goals.account_settings('Example cash ISA','savings','cash_isa')
            key=goals.identity('Example cash ISA','savings')
            goals.interest_rate(key,'4.25','2026-10-01')
            goals.interest_rate(key,'3.75','2026-11-01')
            goals.account_settings('Example cash ISA','savings','cash_isa')
            self.assertEqual(goals.load()['accounts'][key]['interest_rate'],'3.75')
            self.assertEqual(goals.load()['entries'],[])
            with self.assertRaises(ValueError): goals.interest_rate(key,'101','2026-10-01')

    def test_unknown_or_invalid_records_rejected(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(goals,'FILE',Path(folder)/'goals.json'):
            for value in ('NaN','Infinity','-1'):
                with self.assertRaises(ValueError):goals.account_settings('Example','savings','savings',value)
            with self.assertRaises(ValueError):goals.record('unknown','2026-10-01',100)
            with self.assertRaises(ValueError):goals.year_settings(2026,20000,30000,False)

    def test_other_adult_isa_counts_but_junior_is_separate(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(goals,'FILE',Path(folder)/'goals.json'),patch.object(goals,'today',return_value=date(2026,10,4)):
            self.assertEqual(goals.infer('Example Lifetime ISA','investment'),'other_isa')
            self.assertEqual(goals.infer('Example Junior ISA','investment'),'junior_isa')
            goals.account_settings('Example Lifetime ISA','investment','other_isa')
            goals.record(goals.identity('Example Lifetime ISA','investment'),'2026-09-01',500)
            goals.account_settings('Example Junior ISA','investment','junior_isa')
            with self.assertRaises(ValueError):goals.record(goals.identity('Example Junior ISA','investment'),'2026-09-01',100)
            self.assertEqual(goals.review(on=date(2026,10,4),bond_balances=[])['shared']['used'],500)
