import unittest
from datetime import date
from finance.commitments import inferred_netflix_commitment, matching_repayment_transaction, repayment_commitments, summarize_monthly_commitments


class MonthlyRepaymentTests(unittest.TestCase):
    def test_matches_next_month_payment_day_and_amount_without_merchant(self):
        plans = repayment_commitments({'monthly': [], 'instalments': [
            {'name': 'Payment option A', 'amount': 124.92, 'next_payment': '2026-10-21'},
            {'name': 'Payment option B', 'amount': 43.92, 'next_payment': '2026-10-18'},
        ]}, {'debts': []})
        txs = [
            {'date': '2026-09-21', 'description': 'AMAZON.CO.UK', 'amount': -124.92},
            {'date': '2026-09-18', 'description': 'AMAZON.CO.UK', 'amount': -43.92},
        ]
        self.assertEqual(matching_repayment_transaction(plans[0], txs, date(2026, 9, 27)), 0)
        self.assertEqual(matching_repayment_transaction(plans[1], txs, date(2026, 9, 27), {0}), 1)

    def test_date_fallback_rejects_wrong_day_refund_and_reused_transaction(self):
        item = {'amount': 43.92, 'next_payment': '2026-10-18'}
        txs = [
            {'date': '2026-09-12', 'amount': -43.92},
            {'date': '2026-09-18', 'amount': 43.92, 'transaction_type': 'CREDIT'},
            {'date': '2026-09-18', 'amount': -43.92},
        ]
        self.assertEqual(matching_repayment_transaction(item, txs, date(2026, 9, 27)), 2)
        self.assertIsNone(matching_repayment_transaction(item, txs, date(2026, 9, 27), {2}))

    def test_amazon_instalments_get_merchant_match_without_changing_other_repayments(self):
        rows = repayment_commitments({
            'monthly': [], 'instalments': [
                {'name': 'Amazon monthly payments A', 'amount': 124.92, 'remaining_balance': 200},
                {'name': 'Amazon monthly payments B', 'amount': 43.92, 'remaining_balance': 100},
                {'name': 'Other loan', 'amount': 43.92, 'remaining_balance': 100},
            ]}, {'debts': []})
        self.assertEqual([item['match'] for item in rows],
                         [['amazon.co.uk'], ['amazon.co.uk'], []])

    def test_recent_netflix_charge_infers_commitment_once(self):
        transactions = [{'date': '2026-09-25', 'description': 'NETFLIX.COM 203832 LND',
                         'amount': -5.99, 'transaction_type': 'DEBIT'}]
        inferred = inferred_netflix_commitment([], transactions, date(2026, 9, 27))
        self.assertEqual((inferred['name'], inferred['amount'], inferred['match']),
                         ('Netflix', 5.99, ['netflix']))
        self.assertIsNone(inferred_netflix_commitment([inferred], transactions, date(2026, 9, 27)))
        self.assertIsNone(inferred_netflix_commitment([], transactions, date(2026, 11, 15)))

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
