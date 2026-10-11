import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from jinja2 import Environment, FileSystemLoader
from web_control import finance_insights as insights
from finance.projection import build_projection


class InsightTests(unittest.TestCase):
    def fixture(self,status='complete'):
        today=date(2026,10,4)
        balances={'HSBC':{'available':1000},'MONZO':{'available':200},'AMEX':{'current':50}}
        settings={'emergency_buffer':100,'runway_daily_spend':10,'next_payday':'2026-10-10','commitments':[{'name':'Amex repayment','amount':50,'due_date':'2026-10-08'},{'name':'Example bill','amount':200,'due_date':'2026-10-07'}]}
        projection=build_projection(balances,[],[],[],settings,today,bank_status=status)
        return today,balances,projection

    def test_lowest_balance_target_and_private_aggregate_snapshot(self):
        today,balances,projection=self.fixture()
        with tempfile.TemporaryDirectory() as folder,patch.object(insights,'FILE',Path(folder)/'history.json'):
            result=insights.build(projection,balances,{'bank_data_status':'complete','requested_from':'2026-09-05'}, {'total':Decimal(100)}, {'month_total':Decimal(500)},None,{'monthly':{'amount':Decimal(900)}},today)
            self.assertEqual(result['lowest']['date'],date(2026,10,9))
            self.assertEqual(result['lowest']['cash'],Decimal(800))
            self.assertEqual(result['planning']['gap'],100)
            self.assertEqual(insights.FILE.stat().st_mode&0o777,0o600)
            raw=insights.FILE.read_text()
            self.assertNotIn('Example bill',raw)
            self.assertNotIn('account_id',raw)
            environment=Environment(loader=FileSystemLoader('web_control/templates'),autoescape=True)
            from services.source_status import label
            environment.filters['source_status_label']=label
            html=environment.get_template('finance_insights.html').render(url_for=lambda endpoint:"/"+endpoint,insights=result,projection=projection,checked_at=today,bank_data_status='complete',accessible_savings=0,wealth=None)
            self.assertIn('<svg',html)
            self.assertIn('Lowest expected cash balance',html)
            self.assertIn('£800.00',html)
            self.assertIn('Observed income £500',html)
            insights.build(projection,balances,{}, {'total':Decimal(101)}, {'month_total':Decimal(501)},None,None,today)
            self.assertEqual(len(__import__('json').loads(insights.FILE.read_text())),1)

    def test_midmonth_scope_is_preserved_without_whole_month_claim(self):
        today, balances, projection = self.fixture()
        scope = {'monzo': 'first', 'sources': [{'provider': 'MONZO', 'mode': 'first', 'included': 1, 'available': 11}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(insights, 'FILE', Path(folder) / 'history.json'):
            result = insights.build(projection, balances, {'bank_data_status': 'complete', 'requested_from': '2026-10-01', 'collection_scope': scope}, {'total': Decimal(100)}, {'month_total': Decimal(500)}, None, None, today)
            self.assertFalse(result['history'][0]['whole_month'])
            self.assertEqual(result['history'][0]['collection_scope'], scope)

    def test_partial_forecast_withheld_and_unknown_savings(self):
        today,balances,projection=self.fixture('partial')
        with tempfile.TemporaryDirectory() as folder,patch.object(insights,'FILE',Path(folder)/'history.json'):
            result=insights.build(projection,balances,{'bank_data_status':'partial'}, {'total':Decimal(100)}, {'month_total':Decimal(500)},None,None,today)
            self.assertIsNone(result['lowest'])
            self.assertIsNone(result['planning']['spare'])
            self.assertIsNone(result['history'][0]['savings'])
            self.assertFalse(result['history'][0]['whole_month'])

    def test_snapshot_backup_validation_and_missing_values(self):
        from web_control.private_backup import validate
        import json
        row={'month':'2026-10','as_of':'2026-10-04','coverage':'partial','whole_month':False,'income':'100','spending':'50','savings':None,'investments':None,'card_debt':None,'cash':'-10'}
        self.assertIn('finance_monthly_snapshots.json',validate(json.dumps({'version':1,'files':{'finance_monthly_snapshots.json':[row]}}).encode())['files'])
        with self.assertRaises(ValueError): insights.validate([dict(row,income='NaN')])
        with self.assertRaises(ValueError): insights.validate([row,row])
        with tempfile.TemporaryDirectory() as folder,patch.object(insights,'FILE',Path(folder)/'history.json'):
            self.assertIsNone(insights.snapshots(row)[0]['percent'])

    def test_overlapping_match_suggestion_can_be_dismissed(self):
        from web_control import finance_suggestions as suggestions
        today,balances,projection=self.fixture()
        rows=[{'item':{'name':'Example one','amount':10,'match':['EXAMPLE SERVICE']},'transaction':{}}, {'item':{'name':'Example two','amount':20,'match':['EXAMPLE SERVICE']},'transaction':{}}]
        with tempfile.TemporaryDirectory() as folder,patch.object(suggestions,'DISMISSED_FILE',Path(folder)/'dismissed.json'):
            cards=suggestions.build_suggestions(projection,rows,[],[],{'categories':[]},[],[],today)
            overlap=next(c for c in cards if c['title']=='Review overlapping commitment matches')
            suggestions.dismiss_suggestion(overlap['id'],today)
            self.assertNotIn(overlap['id'],[c['id'] for c in suggestions.build_suggestions(projection,rows,[],[],{'categories':[]},[],[],today)])
