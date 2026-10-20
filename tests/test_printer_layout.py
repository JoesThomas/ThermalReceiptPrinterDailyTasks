from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import base64

from PIL import Image
from receipt.capture import RecordingPrinter
from receipt.layout import OrderedPrinter
from receipt.printer_layout import ContentPrinter
from receipt import output


def bitmap():
    stream = BytesIO()
    Image.new('1', (576, 8), 1).save(stream, format='PNG')
    stream.seek(0)
    return stream


class RasterResetPrinter:
    """A compatible printer that loses positioning and needs LF after raster."""
    def __init__(self):
        self.profile = SimpleNamespace(profile_data={'media': {'width': {'pixels': 576}}})
        self.align = 'left'
        self.pending = False
        self.printed = []
        self.images = 0
        self.cuts = 0
    def set(self, **kwargs):
        if not self.pending:
            self.align = kwargs.get('align', self.align)
    def hw(self, command):
        if command == 'init':
            self.pending, self.align = False, 'left'
    def text(self, value):
        if self.pending:
            if value != '\n':
                raise AssertionError('Text sent before raster line was finished')
            self.pending = False
        self.printed.append((self.align, value))
    def image(self, *args, **kwargs):
        self.pending, self.align = True, 'left'
        self.images += 1
    def cut(self):
        self.cuts += 1
    def close(self):
        pass


class PrinterLayoutTests(TestCase):
    def test_immediate_and_deferred_margins_survive_multiple_images(self):
        for deferred in (False, True):
            with self.subTest(deferred=deferred):
                device = RasterResetPrinter()
                recorder = RecordingPrinter(ContentPrinter(device), defer=deferred)
                for name in ('CURRENT CONDITIONS', 'HOURLY WEATHER', 'NEWS', 'FINANCE'):
                    output.left(recorder, name)
                    recorder.image(bitmap())
                    recorder.text('\n')  # Existing renderer spacing is reused.
                    output.line(recorder)
                output.centre(recorder, 'CENTRED HEADING')
                if deferred:
                    self.assertEqual(device.printed, [])
                    recorder.send()
                rows = [(align, row) for align, value in device.printed for row in value.splitlines() if row]
                self.assertEqual([row for align, row in rows if not row.startswith(' ')], ['CENTRED HEADING'])
                self.assertEqual(rows[-1], ('center', 'CENTRED HEADING'))
                self.assertTrue(all(align == 'left' for align, row in rows[:-1]))
                self.assertEqual(device.images, 4)
                self.assertEqual(sum(value == '\n' for _, value in device.printed), 4)
                self.assertIn('HOURLY WEATHER\n', recorder.lines)  # No physical inset saved.

    def test_split_text_keeps_columns_currency_and_one_inset(self):
        device = RasterResetPrinter()
        printer = ContentPrinter(device)
        printer.text('[ ] A ')
        printer.text('task\n\nHSBC'.ljust(10) + ' £1,000.00\n')
        text = ''.join(value for _, value in device.printed)
        self.assertTrue(text.startswith(' [ ] A task\n\n HSBC'))
        self.assertEqual(text.count(' [ ]'), 1)
        self.assertIn('£1,000.00', text)
        printer.image(bitmap())
        printer.text('No renderer newline\n')
        self.assertEqual(device.printed[-1], ('left', ' No renderer newline\n'))

    def test_reordered_pages_use_same_physical_boundary(self):
        device = RasterResetPrinter()
        recorder = RecordingPrinter(ContentPrinter(device), defer=True)
        printer = OrderedPrinter(recorder, ['actions', 'information', 'food', 'finance'])
        printer.begin('information')
        output.left(printer, 'Before graph')
        printer.image(bitmap())
        output.left(printer, 'After graph')
        printer.cut()
        printer.begin('actions')
        output.left(printer, '[ ] Task')
        printer.cut()
        printer.flush()
        recorder.send()
        rows = [value for _, value in device.printed if value.strip()]
        self.assertEqual(rows, [' [ ] Task\n', ' Before graph\n', ' After graph\n'])
        self.assertEqual(device.cuts, 2)

    def test_archive_reprint_and_lazy_hardware_connection(self):
        from receipt import archive
        from receipt.printer import DeferredPhysicalPrinter
        device = RasterResetPrinter()
        calls = []
        lazy = DeferredPhysicalPrinter(lambda: calls.append('open') or device)
        self.assertEqual(calls, [])
        lazy.text('Lazy line\n')
        self.assertEqual(calls, ['open'])
        self.assertEqual(device.printed[-1], ('left', ' Lazy line\n'))
        encoded = 'data:image/png;base64,' + base64.b64encode(bitmap().getvalue()).decode()
        item = {'pages': {'information': 'Before\n[[RECEIPT_IMAGE_0]]\n\nAfter\n'},
                'page_images': {'information': [encoded]}}
        with patch.object(archive, 'load', return_value=item), patch('receipt.printer.open_printer', return_value=device), patch('receipt.recovery.mark'):
            archive.reprint('example', 'information')
        self.assertIn(' After\n', ''.join(value for _, value in device.printed))
        self.assertEqual(device.images, 1)
        self.assertEqual(device.cuts, 1)
