import ast
from datetime import date, datetime
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def income_functions():
    source = ast.parse((ROOT / 'services' / 'live_pipeline.py').read_text(encoding='utf-8'))
    names = {'_is_incoming_transaction', '_incoming_transaction_name',
             '_looks_like_internal_transfer', '_looks_like_salary',
             '_transaction_date', 'analyse_incoming_payments'}
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in names]
    namespace = {'_safe_amount': lambda amount: float(amount or 0),
                 'printer_safe_text': str, 'datetime': datetime, 're': re,
                 'FINANCE_SALARY_KEYWORDS': ('salary', 'payroll', 'wages'),
                 'FINANCE_INTERNAL_TRANSFER_KEYWORDS': ('internal transfer', 'own account',
                                                        'between my accounts', 'savings transfer',
                                                        'credit card payment', 'card repayment')}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT), 'exec'), namespace)
    return namespace['analyse_incoming_payments']


class IncomingClassificationTests(unittest.TestCase):
    def test_salary_reference_and_external_bank_transfer_are_kept(self):
        transactions = [
            {'timestamp': '2026-09-28', 'amount': 2000, 'description': 'Example Employer'},
            {'timestamp': '2026-09-28', 'amount': 30, 'description': 'Bank transfer from friend'},
            {'timestamp': '2026-09-28', 'amount': 20, 'description': 'PAYPAL reimbursement'},
            {'timestamp': '2026-09-28', 'amount': 50, 'description': 'Internal transfer own account'},
            {'timestamp': '2026-09-28', 'amount': 30, 'transaction_type': 'DEBIT',
             'description': 'Debit represented as positive'},
            {'timestamp': '2026-09-28', 'amount': 100, 'description': 'Credit card payment'},
            {'timestamp': '2026-09-28', 'amount': 2100, 'description': 'Monthly payroll'},
        ]
        salary, other = income_functions()(transactions, salary_payee='Example Employer')
        self.assertEqual({item['name'] for item in salary}, {'Example Employer', 'Monthly payroll'})
        self.assertEqual({item['name'] for item in other},
                         {'Bank transfer from friend', 'PAYPAL reimbursement'})


if __name__ == '__main__':
    unittest.main()
