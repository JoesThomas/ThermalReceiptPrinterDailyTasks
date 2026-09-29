import unittest
import ast
from datetime import date
from pathlib import Path
from unittest.mock import patch
from finance.yearly_subscriptions import annual_subscription_rows, next_renewal


class AnnualSubscriptionTests(unittest.TestCase):
    def test_renewal_and_confirmed_bank_match(self):
        yearly = [{'name': 'Annual service', 'amount': 120, 'renewal_date': '2025-09-21',
                   'match': ['service'], 'last_paid': '2025-09-21'}]
        transactions = [{'date': '2026-09-21', 'amount': -120,
                         'description': 'SERVICE UK', 'transaction_type': 'DEBIT'}]
        row = annual_subscription_rows(yearly, transactions, date(2026, 9, 29))[0]
        self.assertEqual(row['next_renewal'], date(2027, 9, 21))
        self.assertEqual(row['bank_paid_date'], date(2026, 9, 21))
        self.assertEqual(row['last_paid_date'], date(2025, 9, 21))

    def test_old_record_and_monthly_charge_do_not_verify_renewal(self):
        yearly = [{'name': 'Annual service', 'amount': 120, 'renewal_date': '2025-10-21',
                   'match': ['service'], 'last_paid': '2025-10-21'}]
        transactions = [{'date': '2026-09-21', 'amount': -10, 'description': 'SERVICE UK'},
                        {'date': '2026-09-21', 'amount': 120, 'description': 'SERVICE REFUND',
                         'transaction_type': 'CREDIT'}]
        row = annual_subscription_rows(yearly, transactions, date(2026, 9, 29))[0]
        self.assertEqual(row['next_renewal'], date(2026, 10, 21))
        self.assertIsNone(row['bank_paid_date'])
        self.assertEqual(row['last_paid_date'], date(2025, 10, 21))

    def test_leap_day_renews_on_last_day_of_february(self):
        self.assertEqual(next_renewal({'renewal_date': '2024-02-29'}, date(2025, 2, 1)),
                         date(2025, 2, 28))
        self.assertEqual(next_renewal({'renewal_date': '2024-02-29'}, date(2028, 2, 1)),
                         date(2028, 2, 29))

    def test_recording_ignores_same_merchant_monthly_payment(self):
        from services import subscriptions as saved
        today = date.today()
        item = {'name': 'Annual service', 'amount': 120,
                'renewal_date': today.isoformat(), 'match': ['service']}
        data = {'monthly': [], 'yearly': [item], 'instalments': []}
        txs = [{'date': today.isoformat(), 'amount': -10, 'description': 'service'},
               {'date': today.isoformat(), 'amount': -120, 'description': 'service'}]
        with patch.object(saved, 'load_subscriptions', return_value=data), \
             patch.object(saved, 'save_subscriptions') as save:
            saved.update_subscriptions_from_transactions(txs)
        self.assertEqual(item['last_paid'], today.isoformat())
        self.assertEqual(item['history'][-1]['amount'], 120)
        save.assert_called_once()

    def test_receipt_separates_annual_entry_and_labels_unverified(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'services/live_pipeline.py')
                           .read_text(encoding='utf-8'))
        node = next(item for item in source.body if isinstance(item, ast.FunctionDef)
                    and item.name == 'print_annual_subscription_status')
        namespace = {'annual_subscription_rows': annual_subscription_rows}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<annual-receipt>', 'exec'), namespace)
        lines = []
        namespace['print_annual_subscription_status'](
            object(), lambda printer, line: lines.append(line),
            lambda printer, char: lines.append(char * 40),
            {'yearly': [{'name': 'Annual service', 'amount': 120,
                         'renewal_date': '2025-10-21', 'last_paid': '2025-10-21'}]},
            [], date(2026, 9, 29))
        self.assertIn('ANNUAL SUBSCRIPTIONS [F+B]', lines)
        self.assertIn('  PAYMENT UNVERIFIED', lines)
        self.assertTrue(any('NEXT 21 Oct 2026' in line for line in lines))
        self.assertTrue(all(len(line) <= 40 for line in lines))


if __name__ == '__main__':
    unittest.main()
