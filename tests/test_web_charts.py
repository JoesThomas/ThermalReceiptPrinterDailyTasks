import unittest
from datetime import date

from web_control.charts import finance_charts, instalment_progress


class WebChartTests(unittest.TestCase):
    def test_chart_totals_use_clean_spending_and_private_categories(self):
        transactions = [
            {'date': '2026-08-30', 'amount': -8, 'type': 'DEBIT', 'description': 'GROCER A'},
            {'date': '2026-09-01', 'amount': -12, 'type': 'DEBIT', 'description': 'GROCER A'},
            {'date': '2026-09-22', 'amount': -20, 'type': 'DEBIT', 'description': 'GROCER A'},
            {'date': '2026-09-22', 'amount': 20, 'type': 'CREDIT', 'description': 'REFUND'},
            {'date': '2026-09-23', 'amount': -100, 'type': 'DEBIT', 'description': 'TRANSFER BETWEEN ACCOUNTS'},
        ]
        commitments = [{'name': 'Bill', 'amount': 30, 'paid': True},
                       {'name': 'Plan', 'amount': 70, 'paid': False, 'category': 'repayment'}]
        result = finance_charts(transactions, commitments, date(2026, 9, 28),
                                rules={'GROCER A': 'FOOD'})
        self.assertEqual(result['spending_total'], 40)
        self.assertEqual(result['weekly_total'], 32)
        self.assertEqual(sum(row['amount'] for row in result['categories']), 40)
        self.assertEqual([row['amount'] for row in result['weeks']], [12, 0, 0, 20])
        self.assertEqual(result['commitments']['paid_percent'], 30)
        self.assertEqual(result['commitments']['due_percent'], 70)

    def test_repayment_progress_needs_consistent_balances(self):
        progress = instalment_progress({'paid_to_date': 60, 'remaining_balance': 40})
        self.assertEqual(progress, {'paid': 60, 'remaining': 40, 'total': 100, 'percent': 60})
        self.assertIsNone(instalment_progress({'total_price': 10, 'remaining_balance': 20}))
        self.assertIsNone(instalment_progress({'remaining_balance': 20}))


if __name__ == '__main__':
    unittest.main()
