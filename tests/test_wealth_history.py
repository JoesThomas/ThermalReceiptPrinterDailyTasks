import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from finance import wealth_history as wealth

class WealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(wealth, 'HISTORY_FILE', Path(self.temp.name)/'history.json')
        self.patcher.start()
        self.today = date(2026,9,30)
    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()
    def record(self, on, value, deposits=None, withdrawals=None, **kw):
        wealth.record('Example ISA','investment',on,value,deposits,withdrawals,today=self.today,**kw)
    def test_balance_change_and_cash_flow_adjustment(self):
        self.record('2026-09-01',1000)
        self.record('2026-09-30',2000,800,100)
        account = wealth.review(self.today)['accounts'][0]
        self.assertEqual(account['change'],Decimal('1000'))
        self.assertEqual(account['percent'],Decimal('100'))
        self.assertEqual(account['growth'],Decimal('300'))
        self.assertEqual(account['net_contributions'],Decimal('700'))
        self.assertTrue(all(len(line)<=40 for line in wealth.receipt_lines(wealth.review(self.today))))
    def test_unknown_flows_not_claimed_as_growth_and_zero_start(self):
        self.record('2026-09-05',0)
        self.record('2026-09-30',2000)
        account = wealth.review(self.today)['accounts'][0]
        self.assertEqual(account['opening']['date'],'2026-09-05')
        self.assertIsNone(account['growth'])
        self.assertIsNone(account['percent'])
    def test_backdating_and_deleting_invalidate_next_interval(self):
        self.record('2026-09-01',1000)
        self.record('2026-09-30',2000,1000,0)
        self.record('2026-09-15',1500,500,0)
        self.assertIsNone(wealth.review(self.today)['accounts'][0]['growth'])
        self.record('2026-09-30',2000,500,0)
        self.assertEqual(wealth.review(self.today)['accounts'][0]['growth'],0)
        middle = next(r for r in wealth.load_history() if r['date']=='2026-09-15')
        wealth.delete(middle['id'])
        self.assertIsNone(wealth.review(self.today)['accounts'][0]['growth'])
    def test_manual_values_prevent_stale_local_overwrite(self):
        self.record('2026-09-01',1000)
        self.record('2026-09-30',2000)
        wealth.capture_local({'accounts':[]},{'updated':'2026-09-30','accounts':[{'name':'Example ISA','value':500}]},self.today)
        self.assertEqual(wealth.review(self.today)['total'],2000)
        _, investments = wealth.apply_latest({'accounts':[]},{'accounts':[{'name':'Example ISA','value':500}]},wealth.review(self.today))
        self.assertEqual(investments['accounts'][0]['value'],2000)
        self.assertEqual(len(wealth.load_history()),2)
    def test_validation_and_previous_month_no_future_leak(self):
        self.record('2026-08-01',1000)
        self.record('2026-08-30',1200,0,0)
        self.record('2026-09-30',2000)
        account = wealth.review(self.today,'2026-08')['accounts'][0]
        self.assertEqual(account['change'],200)
        self.assertEqual(account['closing']['date'],'2026-08-30')
        for value in ['NaN','Infinity','-1']:
            with self.assertRaises(ValueError):
                self.record('2026-09-30',value)
        with self.assertRaises(ValueError):
            self.record('2026-10-01',1000)
