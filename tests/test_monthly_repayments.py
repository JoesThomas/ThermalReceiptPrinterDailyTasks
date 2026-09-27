import unittest
from finance.commitments import repayment_commitments, summarize_monthly_commitments


class MonthlyRepaymentTests(unittest.TestCase):
    def test_adds_instalment_and_loan_without_counting_existing_monthly_row(self):
        subscriptions = {
            'monthly': [{'name': 'Rent', 'amount': 500},
                        {'name': 'Laptop Plan', 'amount': 25}],
            'instalments': [{'name': 'Laptop instalment', 'monthly_commitment_name': 'Laptop Plan',
                            'amount': 25, 'remaining_balance': 100},
                           {'name': 'Festival Plan', 'amount': 20.46, 'remaining_balance': 142.86,
                            'match': ['festival finance']},
                           {'name': 'Paid off', 'amount': 15, 'remaining_balance': 0}],
        }
        settings = {'debts': [
            {'name': 'Festival Plan', 'balance': 142.86, 'monthly_payment': 20.46},
            {'name': 'Mortgage', 'balance': 180000, 'monthly_payment': 950},
            {'name': 'Loan', 'balance': 100, 'monthly_payment': 0},
        ]}
        rows = repayment_commitments(subscriptions, settings)
        self.assertEqual([(item['name'], item['amount']) for item in rows],
                         [('Festival Plan', 20.46), ('Mortgage', 950.0)])
        self.assertEqual(rows[0]['match'], ['festival finance'])

    def test_repayments_are_in_paid_and_due_totals_once(self):
        status = summarize_monthly_commitments([
            {'name': 'Rent', 'amount': 500, 'paid': False},
            {'name': 'Savings', 'amount': 40, 'category': 'savings', 'paid': False},
            {'name': 'Festival Plan', 'amount': 20.46, 'category': 'repayment', 'paid': True},
            {'name': 'Mortgage', 'amount': 950, 'category': 'repayment', 'paid': False},
        ])
        self.assertEqual(status['paid_total'], 20.46)
        self.assertEqual(status['due_bills'], 500)
        self.assertEqual(status['due_savings'], 40)
        self.assertEqual(status['due_repayments'], 950)
        self.assertEqual(status['remaining_total'], 1490)

if __name__ == '__main__':
    unittest.main()
