import json
import tempfile
import unittest
from pathlib import Path
from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from storage import PrivateStore, PrivateStateError
from finance.money import parse
from services.source_status import state, health, SourceState
from services.finance_source import collect, FinanceDependencies


class SharedBoundaryTests(unittest.TestCase):
    def test_damaged_private_file_is_preserved_and_updates_are_locked(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            store=PrivateStore(path,default=lambda:{'count':0})
            def increment(_):
                store.update(lambda row:row.update(count=row['count']+1))
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(increment,range(20)))
            self.assertEqual(store.read()['count'],20)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            path.write_text('damaged')
            with self.assertRaises(PrivateStateError):store.update(lambda row:row.update(count=0))
            self.assertEqual(path.read_text(),'damaged')

    def test_exact_money_and_shared_source_states(self):
        self.assertEqual(parse('0.005'),Decimal('0.01'))
        self.assertIsNone(parse('NaN'));self.assertIsNone(parse(True))
        self.assertEqual(state('Loaded'),SourceState.FRESH)
        self.assertEqual(state('Disabled by first-account setting'),SourceState.DISABLED)
        self.assertEqual(state('cached after error'),SourceState.CACHED)
        self.assertEqual(health('complete'),'healthy')
        self.assertEqual(health('partial'),'degraded')
        self.assertEqual(health('unavailable'),'failed')

    def test_extracted_finance_collector_preserves_selected_scope(self):
        seen=[]
        values={name:(lambda *a,**kw:[]) for name in FinanceDependencies.__dataclass_fields__}
        values.update(today=lambda:date(2026,10,4),FINANCE_TRANSACTION_LOOKBACK_DAYS=90,
            _initial_truelayer_refresh_token=lambda p:'token',_refresh_truelayer_access_token=lambda p,t:p,
            _truelayer_account_ids=lambda token:['h1'] if token=='HSBC' else ['m1','m2'],
            _truelayer_card_ids=lambda token:['a1'],
            _dedupe_regular_payments=lambda rows:rows,
            _dedupe_subscriptions_against_regular=lambda *a:[],
            _monthlyised_spend=lambda *a,**kw:0,_last_n_day_spend=lambda *a:0,
            _incoming_total=lambda *a,**kw:0,analyse_incoming_payments=lambda *a,**kw:([],[]),
            load_receipt_settings=lambda:{'finance':{}})
        def transactions(token,kind,identity,*a,**kw):seen.append(identity);return []
        values['_truelayer_transactions']=transactions
        with patch('finance.transaction_sources.load',return_value={'monzo':'first'}),patch('finance.premium_bonds.capture'):
            summary=collect(FinanceDependencies(**values))[4]
        self.assertEqual(seen,['h1','m1','a1'])
        monzo=next(row for row in summary['collection_scope']['sources'] if row['provider']=='MONZO')
        self.assertEqual((monzo['included'],monzo['available']),(1,2))
        self.assertNotIn('m1',json.dumps(summary['collection_scope']))
