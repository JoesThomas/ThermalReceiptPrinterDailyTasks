import unittest
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from finance.receipt import (calculate_debt_and_payday, _amount_rows,
                             print_integrated_finance, print_incoming_payments,
                             _calendar_occurrence, _forecast_events)

class FinanceReceiptTests(unittest.TestCase):
    def test_cash_runway_uses_bank_cash_and_scheduled_card_payment_not_total_debt(self):
        import finance.receipt as receipt
        import tempfile
        import json
        from pathlib import Path
        lines = []
        class Printer:
            def text(self, value):
                pass
            def set(self, **kwargs):
                pass
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.json'
            settings.write_text(json.dumps({'runway_daily_spend': 10, 'commitments': [
                {'name': 'Amex repayment', 'amount': 100, 'due_date': '2026-09-30'}]}), encoding='utf-8')
            receipt.print_integrated_finance(
                Printer(), lambda printer, value: lines.append(value),
                lambda printer, char='-': None,
                {'HSBC': {'available': 500}, 'MONZO': {'available': 100},
                 'AMEX': {'current': 900}}, transactions=[],
                finance_settings_file=settings, today=date(2026, 9, 29))
        self.assertIn('RUNWAY / DATED PAYMENTS [E]', lines)
        self.assertTrue(any('51 DAYS' in row for row in lines))
        self.assertTrue(any('£100.00' in row and 'LISTED PAYMENTS' in row for row in lines))

    def test_incoming_section_lists_salary_and_every_other_payment_in_window(self):
        lines = []
        class Printer:
            def text(self, value):
                lines.extend(value.splitlines())
        summary = {
            'salary_incomings': [{'date': date(2026, 9, 20), 'name': 'Example Payroll', 'amount': 2000}],
            'other_incomings': [
                {'date': date(2026, 9, 28 - index), 'name': f'Other source {index}', 'amount': 10}
                for index in range(7)
            ] + [{'date': date(2026, 8, 1), 'name': 'Old income', 'amount': 500}],
        }
        print_incoming_payments(Printer(), lambda p, value: lines.append(value),
                                lambda p, char: lines.append(char * 40),
                                summary, 600, date(2026, 9, 28))
        self.assertIn('SALARY PAYMENTS (1)', lines)
        self.assertIn('OTHER INCOMING PAYMENTS (7)', lines)
        self.assertTrue(any('£2,070.00' in row for row in lines))
        self.assertTrue(any('£1,470.00' in row for row in lines))
        self.assertTrue(all(any(f'OTHER SOURCE {index}' in row for row in lines)
                            for index in range(7)))
        self.assertFalse(any('OLD INCOME' in row for row in lines))
        self.assertTrue(all(len(row) <= 40 for row in lines))

    def test_rent_and_winnings_are_grouped_without_losing_each_payment(self):
        lines = []
        class Printer:
            def text(self, value):
                lines.extend(value.splitlines())
        summary = {'salary_incomings': [], 'other_incomings': [
            {'date': date(2026, 9, 28), 'name': 'Rent from tenant', 'category': 'RENT RECEIVED', 'amount': 800},
            {'date': date(2026, 9, 27), 'name': 'Premium Bonds', 'category': 'PREMIUM BONDS', 'amount': 25},
            {'date': date(2026, 9, 26), 'name': 'Bet365', 'category': 'BET WINNINGS', 'amount': 35},
            {'date': date(2026, 9, 25), 'name': 'Friend', 'category': 'FRIENDS / FAMILY', 'amount': 12},
        ]}
        print_incoming_payments(Printer(), lambda p, value: lines.append(value),
                                lambda p, char: lines.append(char * 40),
                                summary, 100, date(2026, 9, 28))
        self.assertTrue(any('RENT RECEIVED (1)' in row and '£800.00' in row for row in lines))
        self.assertTrue(any('28 SEP RENT FROM TENANT' in row and '£800.00' in row for row in lines))
        self.assertTrue(any('TOTAL IN' in row and '£872.00' in row for row in lines))
        self.assertTrue(any('£772.00' in row for row in lines))
        self.assertTrue(all(len(row) <= 40 for row in lines))

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

    def test_receipt_identifies_bank_file_and_estimate_sources(self):
        import finance.receipt as receipt
        previous_debug = receipt.DEBUG_SPENDING
        receipt.DEBUG_SPENDING = False
        class Printer:
            def __init__(self):
                self.lines = []
            def text(self, value):
                self.lines.extend(value.splitlines())
            def set(self, **kwargs):
                pass
        printer = Printer()
        import tempfile
        import json
        from pathlib import Path
        settings = {'reviewed_on': '2026-09-27', 'next_payday': '2026-10-30',
                    'debts': [{'name': 'Plan', 'type': 'payment_plan', 'balance': 100}],
                    'runway_daily_spend': 10, 'commitments': [
                        {'name': 'Amex repayment', 'amount': 50, 'due_date': '2026-10-20'},
                        {'name': 'Plan', 'amount': 10, 'due_date': '2026-10-21'}]}
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'finance.json'
                path.write_text(json.dumps(settings), encoding='utf-8')
                print_integrated_finance(
                    printer, lambda p, value: p.text(value + '\n'),
                    lambda p, char='-': p.text(char * 40 + '\n'),
                    {'HSBC': {'available': 500}, 'MONZO': {'available': 100},
                     'AMEX': {'current': 50}}, transactions=[],
                    finance_settings_file=path, today=date(2026, 9, 27))
        finally:
            receipt.DEBUG_SPENDING = previous_debug
        self.assertTrue(any('HSBC [B]' in line for line in printer.lines))
        self.assertTrue(any('PLAN [F]' in line for line in printer.lines))
        self.assertTrue(any('SAFE TO SPEND [E]' in line for line in printer.lines))
        self.assertTrue(all(len(line) <= 40 for line in printer.lines))

    def test_long_name_keeps_amount_and_fits_receipt(self):
        rows = _amount_rows('Very long payment plan description on paper', 123.45)
        self.assertTrue(all(len(row) <= 40 for row in rows))
        self.assertTrue(any('£123.45' in row for row in rows))

    def test_negative_amount_puts_minus_before_pound_sign(self):
        self.assertEqual(_amount_rows('Known cash change', -500)[0],
                         'KNOWN CASH CHANGE               -£500.00')
        self.assertEqual(_amount_rows('Credit', 0)[0][-5:], '£0.00')

    def test_monthly_payday_and_bill_roll_without_losing_day_31(self):
        settings = {
            'next_payday': '2026-01-31', 'payday_repeat': 'monthly',
            'commitments': [{'name': 'Bill', 'due_date': '2026-01-31',
                             'repeat': 'monthly', 'amount': 25}],
        }
        result = calculate_debt_and_payday(100, 0, [], settings, date(2026, 2, 28))
        self.assertEqual(result['payday'], date(2026, 3, 31))
        self.assertEqual([item['due_date'] for item in result['commitments']],
                         ['2026-02-28'])
        self.assertEqual(result['safe'], Decimal('75.00'))
        self.assertEqual(_calendar_occurrence(date(2026, 1, 31),
                         date(2026, 4, 1), 'monthly'), date(2026, 4, 30))

    def test_recurring_bills_are_counted_each_time_before_payday(self):
        settings = {'next_payday': '2026-04-30',
                    'commitments': [{'name': 'Plan', 'due_date': '2026-01-15',
                                     'repeat': 'monthly', 'amount': 20}]}
        result = calculate_debt_and_payday(100, 0, [], settings, date(2026, 2, 1))
        self.assertEqual(result['committed'], Decimal('60.00'))
        self.assertEqual([item['due_date'] for item in result['commitments']],
                         ['2026-02-15', '2026-03-15', '2026-04-15'])

    def test_yearly_leap_day_restores_in_leap_year(self):
        self.assertEqual(_calendar_occurrence(date(2024, 2, 29),
            date(2025, 2, 1), 'yearly'), date(2025, 2, 28))
        self.assertEqual(_calendar_occurrence(date(2024, 2, 29),
            date(2028, 2, 1), 'yearly'), date(2028, 2, 29))

    def test_monthly_forecast_events_roll_too(self):
        events = [{'date': '2026-10-01', 'repeat': 'monthly', 'amount': -500}]
        upcoming = _forecast_events(events, date(2026, 11, 27), date(2026, 12, 27))
        self.assertEqual([item['date'] for item in upcoming], ['2026-12-01'])

    def test_expired_payday_does_not_print_allowance(self):
        result = calculate_debt_and_payday(100, 0, [],
            {'next_payday': '2026-09-01'}, date(2026, 9, 30))
        self.assertNotIn('daily', result)
