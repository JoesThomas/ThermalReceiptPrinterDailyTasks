import unittest
from datetime import date
from decimal import Decimal
from finance.receipt import calculate_debt_and_payday, _amount_rows

class FinanceReceiptTests(unittest.TestCase):
    def test_live_amex_and_instalment_take_precedence(self):
        settings = {
            'next_payday': '2026-10-05', 'emergency_buffer': 100,
            'debts': [{'name': 'Amex', 'balance': 999, 'type': 'credit_card'},
                      {'name': 'Plan', 'balance': 900, 'type': 'payment_plan'},
                      {'name': 'House', 'balance': 100000, 'type': 'mortgage'}],
            'commitments': [{'name': 'Rent', 'due_date': '2026-10-01', 'amount': 200},
                            {'name': 'Later', 'due_date': '2026-10-05', 'amount': 200}],
        }
        result = calculate_debt_and_payday(1000, 50,
            [{'name': 'Plan', 'remaining_balance': 150, 'amount': 20}],
            settings, date(2026, 9, 30))
        self.assertEqual(result['short_term'], Decimal('200.00'))
        self.assertEqual(result['long_term'], Decimal('100000.00'))
        self.assertEqual(result['net_liquid'], Decimal('800.00'))
        self.assertEqual(result['safe'], Decimal('700.00'))
        self.assertEqual(result['daily'], Decimal('140.00'))

    def test_long_name_keeps_amount_and_fits_receipt(self):
        rows = _amount_rows('Very long payment plan description on paper', 123.45)
        self.assertTrue(all(len(row) <= 40 for row in rows))
        self.assertTrue(any('£123.45' in row for row in rows))

    def test_negative_amount_puts_minus_before_pound_sign(self):
        self.assertEqual(_amount_rows('Known cash change', -500)[0],
                         'KNOWN CASH CHANGE               -£500.00')
        self.assertEqual(_amount_rows('Credit', 0)[0][-5:], '£0.00')

    def test_expired_payday_does_not_print_allowance(self):
        result = calculate_debt_and_payday(100, 0, [],
            {'next_payday': '2026-09-01'}, date(2026, 9, 30))
        self.assertNotIn('daily', result)
