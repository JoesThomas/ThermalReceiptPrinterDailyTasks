import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from receipt.capture import RecordingPrinter, load_capture
from receipt.visual_sample import example_pages
from web_control.payments import monthly_payments


class FakePrinter:
    def __init__(self):
        self.printed = []

    def text(self, value):
        self.printed.append(value)

    def set(self, **kwargs):
        pass

    def image(self, *args, **kwargs):
        pass

    def cut(self):
        pass


class MonthlyPaymentTests(unittest.TestCase):
    def test_identical_charges_stay_separate_but_duplicate_ids_are_removed(self):
        transactions = [
            {'date': '2026-09-18', 'amount': -5.50, 'type': 'DEBIT', 'description': 'THE EXAMPLE PUB'},
            {'date': '2026-09-18', 'amount': -5.50, 'type': 'DEBIT', 'description': 'THE EXAMPLE PUB'},
            {'date': '2026-09-19', 'amount': -10.00, 'type': 'DEBIT', 'description': 'BAKERY', 'transaction_id': 'one'},
            {'date': '2026-09-19', 'amount': -10.00, 'type': 'DEBIT', 'description': 'BAKERY', 'transaction_id': 'one'},
            {'date': '2026-09-20', 'amount': 5.50, 'type': 'CREDIT', 'description': 'REFUND'},
            {'date': '2026-09-20', 'amount': -100, 'type': 'DEBIT', 'description': 'INTERNAL TRANSFER'},
        ]
        summary = monthly_payments(transactions, date(2026, 9, 28))
        self.assertEqual(summary['total'], Decimal('21.00'))
        self.assertEqual(summary['count'], 3)
        self.assertEqual(summary['merchants'][0]['name'], 'THE EXAMPLE PUB')
        self.assertEqual([row['amount'] for row in summary['merchants'][0]['payments']],
                         [Decimal('5.50'), Decimal('5.50')])

    def test_marketplace_order_refs_combine_and_outside_month_is_ignored(self):
        transactions = [
            {'date': '2026-09-18', 'amount': -12.00, 'type': 'DEBIT', 'description': 'AMZNMKTPLACE*ABC123456'},
            {'date': '2026-09-22', 'amount': -13.00, 'type': 'DEBIT', 'description': 'AMAZON.CO.UK*XYZ123456'},
            {'date': '2026-08-31', 'amount': -5.00, 'type': 'DEBIT', 'description': 'AMAZON.CO.UK'},
        ]
        summary = monthly_payments(transactions, date(2026, 9, 28))
        self.assertEqual(summary['merchants'][0]['name'], 'Amazon')
        self.assertEqual(summary['merchants'][0]['amount'], Decimal('25.00'))
        self.assertEqual(summary['merchants'][0]['count'], 2)


class ReceiptCaptureTests(unittest.TestCase):
    def test_last_print_is_saved_per_page_and_keeps_older_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'last.json'
            printer = FakePrinter()
            capture = RecordingPrinter(printer)
            capture.set(align='center')
            capture.text('TITLE\n')
            capture.set(align='left')
            capture.text('Item £2.00\n')
            capture.cut()
            capture.save('finance', path=path)
            self.assertEqual(printer.printed, ['TITLE\n', 'Item £2.00\n'])
            self.assertIn('TITLE', load_capture(path)['pages']['finance'])
            other = RecordingPrinter(FakePrinter())
            other.text('Weather\n')
            other.cut()
            other.save('information', path=path)
            self.assertEqual(set(load_capture(path)['pages']), {'information', 'finance'})

    def test_example_has_four_paper_pages(self):
        pages = example_pages(date(2026, 9, 28))
        self.assertEqual(set(pages), {'information', 'actions', 'food', 'finance'})
        self.assertIn('MONTHLY COMMITMENTS', pages['finance'])


if __name__ == '__main__':
    unittest.main()
