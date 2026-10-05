import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from storage import PrivateStore, PrivateStateError
from receipt.layout import amount_rows, progress_bar
from receipt.local_time import uk_receipt_time
from receipt import preview_progress
from web_control.job_status import save


class ConsistentLifecycleTests(unittest.TestCase):
    def test_legacy_migration_is_non_destructive_and_future_schema_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private.json'
            legacy = {'plans': ['kept']}
            path.write_text(json.dumps(legacy))
            store = PrivateStore(path, default=dict, schema_version=1,
                                 migrations={0: lambda value: {**value, 'enabled': True}})
            self.assertEqual(store.read()['plans'], ['kept'])
            self.assertEqual(json.loads(path.read_text()), legacy)
            store.update(lambda value: value.update(name='example'))
            self.assertEqual(json.loads(path.read_text())['schema_version'], 1)
            path.write_text('{"schema_version": 20}')
            with self.assertRaises(PrivateStateError): store.update(lambda value: value.clear())
            self.assertEqual(path.read_text(), '{"schema_version": 20}')

    def test_stage_timings_are_retained_across_worker_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            saved = save(path, 'running')
            saved['stage_started_at'] = '2026-10-05T10:00:00+00:00'
            path.write_text(json.dumps(saved))
            with patch.object(preview_progress, 'STATUS', path), patch.dict(os.environ, {'RECEIPT_LIVE_PREVIEW': '1'}), patch.object(preview_progress, 'datetime') as clock:
                clock.now.return_value = datetime(2026,10,5,10,0,3,tzinfo=timezone.utc)
                clock.fromisoformat.side_effect = datetime.fromisoformat
                preview_progress.report('Fetching calendar', 1, 5)
            ended = save(path, 'completed')
            self.assertEqual(ended['timings'][0]['seconds'], 3)
            self.assertEqual(ended['stages'], ['Fetching calendar'])
            self.assertEqual(ended['job_id'], saved['job_id'])

    def test_receipt_columns_progress_and_clock_transition(self):
        for amount in (-12.345, 1000000):
            lines = amount_rows('A lengthy commitment name ' * 3, amount)
            self.assertTrue(all(len(line) <= 40 for line in lines))
            self.assertEqual(len(lines[-1]), 40)
        self.assertEqual(progress_bar(60), '[#########.......] 60%')
        self.assertEqual(uk_receipt_time('2026-10-25T00:30:00Z'), '25 Oct 2026, 01:30 BST')
        self.assertEqual(uk_receipt_time('2026-10-25T01:30:00Z'), '25 Oct 2026, 01:30 GMT')
        self.assertEqual(uk_receipt_time('2026-10-04T23:30:00Z'), '05 Oct 2026, 00:30 BST')

    def test_anonymous_delivery_and_payment_fixture(self):
        from actions.delivery_summary import summary_lines
        from domain_models import Transaction
        rows = json.loads(Path('tests/fixtures/receipt_integrations.json').read_text())
        lines = summary_lines(rows['deliveries'], lambda value: value['carrier'], lambda value: 'Expected tomorrow')
        self.assertEqual(sum('[ ]' in line for line in lines), 1)
        self.assertLess(next(i for i,line in enumerate(lines) if '[ ]' in line), lines.index('Expected tomorrow'))
        transactions = [Transaction.from_mapping(row) for row in rows['transactions']]
        self.assertEqual(str(transactions[0].amount), '800.00')
        self.assertEqual(str(transactions[1].amount), '-124.92')

    def test_worker_cannot_release_a_replacement_lock(self):
        from web_control.job_runtime import release_owned_lock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lock'
            path.write_text('200')
            release_owned_lock(path, 100)
            self.assertTrue(path.exists())
            release_owned_lock(path, 200)
            self.assertFalse(path.exists())

    def test_compression_keeps_the_chosen_section_order(self):
        from receipt.model import ReceiptDocument, ReceiptSection
        from receipt.renderer import compress_if_needed
        document = ReceiptDocument('example', [ReceiptSection('first', 'First', ['a'] * 4, 1), ReceiptSection('optional', 'Optional', ['b'] * 4, 2, True), ReceiptSection('last', 'Last', ['c'] * 4, 100)])
        with patch('receipt.renderer.MAX_RECEIPT_LINES', {'example': 12}):
            result = compress_if_needed(document)
        self.assertEqual([section.key for section in result.sections], ['first', 'last'])

    def test_subscription_migration_retains_contracts_and_repayments(self):
        from finance.subscription_store import load, save
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'subscriptions.json'
            old = {'monthly': [{'name': 'Example broadband', 'amount': 30, 'end_date': '2028-10-01'}], 'instalments': [{'name': 'Example instrument', 'monthly_payment': 124.92}], 'custom_note': 'retained'}
            path.write_text(json.dumps(old))
            value = load(path)
            self.assertEqual(value['monthly'], old['monthly'])
            self.assertEqual(value['instalments'], old['instalments'])
            save(path, value)
            self.assertEqual(load(path)['custom_note'], 'retained')
            self.assertEqual(load(path)['schema_version'], 1)
