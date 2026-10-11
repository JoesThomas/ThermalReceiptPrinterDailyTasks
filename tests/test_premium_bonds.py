import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from finance import premium_bonds as bonds

class PremiumBondsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.patch=patch.object(bonds,'FILE',Path(self.directory.name)/'bonds.json');self.patch.start()
        self.today=date(2026,10,2)
    def tearDown(self):
        self.patch.stop();self.directory.cleanup()
    def test_equal_winnings_and_balance_are_100_percent(self):
        bonds.record('balance','2025-01-01',10000,self.today)
        bonds.record('prize','2025-09-01',10000,self.today)
        result=bonds.review(self.today,2025)
        self.assertEqual(result['percent'],Decimal(100))
        self.assertFalse(result['full_year'])
        bonds.confirm(2025,self.today)
        self.assertTrue(bonds.review(self.today,2025)['full_year'])
    def test_changing_balance_is_weighted_by_days_and_not_annualised(self):
        today=date(2026,1,4)
        bonds.record('balance','2026-01-01',100,today)
        bonds.record('balance','2026-01-03',300,today)
        bonds.record('prize','2026-01-04',20,today)
        result=bonds.review(today)
        self.assertEqual(result['average'],Decimal(200))
        self.assertEqual(result['percent'],Decimal(10))
        self.assertFalse(result['full_year'])
    def test_prizes_before_first_balance_are_not_used_in_return(self):
        bonds.record('prize','2026-01-01',25,self.today)
        bonds.record('balance','2026-09-01',100,self.today)
        bonds.record('prize','2026-09-02',5,self.today)
        result=bonds.review(self.today)
        self.assertEqual(result['total'],Decimal(30))
        self.assertEqual(result['period_total'],Decimal(5))
        self.assertEqual(result['percent'],Decimal(5))
    def capture(self,rows):
        bonds.capture(rows,lambda tx:'PREMIUM BONDS',lambda tx:tx['amount']>0,
                      lambda tx:False,lambda tx:date.fromisoformat(tx['date']))
    def test_imports_are_idempotent_manual_match_and_exclusion_survives(self):
        bonds.record('prize','2026-09-01',25,self.today)
        row={'date':'2026-09-01','amount':25,'transaction_id':'synthetic-1','description':'Example prize'}
        self.capture([row]);self.capture([row])
        self.assertEqual(len(bonds.load()['prizes']),1)
        self.assertNotIn('synthetic-1',bonds.FILE.read_text())
        bonds.remove('prize',bonds.load()['prizes'][0]['id'])
        self.capture([row])
        self.assertEqual(bonds.review(self.today)['total'],0)
    def test_same_date_and_amount_distinct_ids_remain_distinct(self):
        rows=[{'date':'2026-09-01','amount':25,'transaction_id':str(i)} for i in (1,2)]
        self.capture(rows);self.capture(rows)
        self.assertEqual(bonds.review(self.today)['total'],50)
    def test_fallback_duplicates_keep_occurrences_across_refresh(self):
        row={'date':'2026-09-01','amount':25,'reference':'Synthetic prize'}
        self.capture([row,row]);self.capture([row,row])
        self.assertEqual(bonds.review(self.today)['total'],50)
    def test_zero_missing_invalid_future_and_leap_year(self):
        bonds.record('prize','2024-02-29',10,self.today)
        self.assertIsNone(bonds.review(self.today,2024)['percent'])
        bonds.record('balance','2024-01-01',0,self.today)
        self.assertIsNone(bonds.review(self.today,2024)['percent'])
        for amount in ('NaN','Infinity',-1):
            with self.assertRaises(ValueError):bonds.record('balance','2026-01-01',amount,self.today)
        with self.assertRaises(ValueError):bonds.record('balance','2027-01-01',100,self.today)
        self.assertTrue(any('INCOMPLETE' in row for row in bonds.receipt_lines(date(2024,12,31))))
