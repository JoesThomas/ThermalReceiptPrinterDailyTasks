from unittest import TestCase
from unittest.mock import Mock, patch

from receipt.profile import COLUMNS
from receipt import output, archive
from receipt.sections import print_calendar
from finance.receipt_text import ReceiptText


class ReceiptWidthTests(TestCase):
    def test_profile_wraps_full_width_and_centres_only_headings(self):
        self.assertEqual(COLUMNS, 48)
        rows = []
        printer = Mock()
        printer.text.side_effect = rows.append
        output.heading(printer, "TODAY'S CALENDAR")
        output.wrapped(printer, 'A' * 20 + ' ' + 'B' * 22)
        output.line(printer)
        self.assertEqual(rows, ["TODAY'S CALENDAR".center(48) + '\n', 'A' * 20 + ' ' + 'B' * 22 + '\n', '-' * 48 + '\n'])
        self.assertTrue(all(len(row.rstrip('\n')) <= 48 for row in rows))

    def test_calendar_heading_and_long_event_use_same_column(self):
        rows, widths = [], []
        def wrapped(printer, text, width):
            widths.append(width)
            rows.append(text)
        print_calendar(Mock(), [{'time': '09:20', 'title': 'An appointment', 'location': 'A location'}],
                       print_line=lambda *args: None, left=lambda p, s: rows.append(s), print_wrapped=wrapped)
        self.assertEqual(rows[0], "TODAY'S CALENDAR".center(48))
        self.assertTrue(rows[1].startswith('[ ] 09:20'))
        self.assertEqual(widths, [48, 48])

    def test_amounts_and_test_receipt_headings_use_48_columns(self):
        page = ReceiptText()
        page.section('SAVINGS')
        page.amount('Account balance', 1234)
        rows = page.render().splitlines()
        self.assertEqual(rows[0], '-' * 48)
        self.assertEqual(rows[1].rstrip(), 'SAVINGS'.center(48).rstrip())
        self.assertEqual(len(rows[-1]), 48)
        self.assertTrue(rows[-1].startswith('Account balance'))
        self.assertTrue(rows[-1].endswith('£1,234.00'))

    def test_old_42_column_archive_keeps_its_original_physical_inset(self):
        from receipt.printer_layout import ContentPrinter
        widths = []
        original = ContentPrinter.text
        def record(printer, text):
            widths.append(printer.columns)
            return original(printer, text)
        with patch.object(archive, 'load', return_value={'pages': {'actions': '-' * 42 + '\nOld receipt\n'}}), patch('receipt.printer.open_printer', return_value=Mock()), patch('receipt.recovery.mark'), patch.object(ContentPrinter, 'text', record):
            archive.reprint('old', 'actions')
        self.assertEqual(set(widths), {42})
