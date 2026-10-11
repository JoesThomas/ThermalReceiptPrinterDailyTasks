import unittest
from datetime import date, timedelta
from decimal import Decimal
from web_control.payments import cash_flow_review, incoming_review


class IncomeReviewTests(unittest.TestCase):
    def test_groups_recent_income_and_month_separately(self):
        today = date(2026, 9, 29)
        income = incoming_review(
            [{'date': today, 'name': 'Employer', 'amount': 2000}],
            [{'date': date(2026, 9, 21), 'name': 'Rent', 'category': 'RENT RECEIVED', 'amount': 800},
             {'date': date(2026, 8, 31), 'name': 'Refund', 'category': 'OTHER IN', 'amount': 20},
             {'date': date(2026, 8, 20), 'name': 'Old', 'category': 'OTHER IN', 'amount': 500}],
            today)
        self.assertEqual(income['total'], Decimal('2820.00'))
        self.assertEqual(income['month_total'], Decimal('2800.00'))
        self.assertEqual(income['month_count'], 2)
        self.assertEqual([item['name'] for item in income['categories']],
                         ['Salary', 'Rent Received', 'Other In'])
        self.assertEqual(income['categories'][0]['percent'], 100)

    def test_cash_flow_uses_same_thirty_day_boundary_for_income_and_spend(self):
        today = date(2026, 9, 29)
        income = incoming_review([], [{'date': today, 'name': 'Rent', 'amount': 800}], today)
        payments = [
            {'date': today.isoformat(), 'spend_amount': 120},
            {'date': (today - timedelta(days=29)).isoformat(), 'spend_amount': 30},
            {'date': (today - timedelta(days=30)).isoformat(), 'spend_amount': 999},
        ]
        flow = cash_flow_review(income, payments, today)
        self.assertEqual((flow['income'], flow['outgoing'], flow['net']),
                         (Decimal('800.00'), Decimal('150.00'), Decimal('650.00')))
        self.assertEqual(len(flow['weeks']), 4)
        self.assertEqual(flow['weeks'][-1]['income'], Decimal('800.00'))
        self.assertEqual(sum((item['outgoing'] for item in flow['weeks']), Decimal('0.00')),
                         Decimal('120.00'))


if __name__ == '__main__':
    unittest.main()
