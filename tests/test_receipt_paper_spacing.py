"""Verify actual cutter bytes, final-line safety and legacy daily preferences."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from pathlib import Path
import json
import receipt_settings
from escpos.printer import Dummy
from receipt.printer_layout import ContentPrinter
from receipt.capture import RecordingPrinter
from receipt.layout import OrderedPrinter, validate
from receipt_settings import validate_settings


class PaperSpacingTests(TestCase):
    def test_default_cut_has_only_cutter_position_feed_and_finishes_last_line(self):
        device = Dummy()
        printer = ContentPrinter(device)
        printer.text('\n  \nFinal footer')
        printer.cut()
        raw = device.output
        self.assertIn(b' Final footer\n\x1dVA\x00', raw)
        self.assertNotIn(b'\x1bd\x06', raw)  # No library six-line feed.
        self.assertNotIn(b'\n\n', raw)
        printer.text('\n\nNext receipt\n')
        self.assertTrue(device.output.endswith(b' Next receipt\n'))

    def test_partial_only_profile_and_unknown_profile_fallback(self):
        device = Mock()
        device.profile = SimpleNamespace(supports=lambda name: name == 'paperPartCut')
        printer = ContentPrinter(device)
        printer.cut()
        device._raw.assert_called_once_with(b'\x1dVB\x00')
        device.cut.assert_not_called()
        device = Mock()
        device.profile = SimpleNamespace()
        ContentPrinter(device).cut()
        device.cut.assert_called_once_with()
        device._raw.assert_not_called()

    def test_explicit_cut_options_are_preserved(self):
        device = Dummy()
        ContentPrinter(device).cut(mode='PART', feed=True)
        self.assertIn(b'\x1bd\x06', device.output)

    def test_deferred_and_reordered_pages_trim_only_leading_blank_lines(self):
        for reordered in (False, True):
            with self.subTest(reordered=reordered):
                device = Dummy()
                recorder = RecordingPrinter(ContentPrinter(device), defer=True)
                printer = OrderedPrinter(recorder, ['actions','information']) if reordered else recorder
                for name in ('information', 'actions'):
                    if reordered:
                        printer.begin(name)
                    printer.text('\n\n')
                    printer.text(name + '\n\nInside\n')
                    printer.cut()
                if reordered:
                    printer.flush()
                recorder.send()
                self.assertEqual(device.output.count(b'\x1dVA\x00'), 2)
                self.assertEqual(device.output.count(b'\n\n'), 2)  # Intentional internal gaps only.
                self.assertNotIn(b'\x1bd\x06', device.output)

    def test_legacy_daily_detail_is_ignored_and_finance_choice_remains_separate(self):
        for detail in ('compact', 'detailed'):
            layout = validate({'detail': detail, 'paper_saver': True})
            self.assertNotIn('detail', layout)
            raw = {'layout': {'detail': detail}}
            validate_settings(raw)
            with TemporaryDirectory() as folder:
                path = Path(folder) / 'settings.json'
                path.write_text(json.dumps(raw))
                with patch.object(receipt_settings, 'SETTINGS_FILE', path):
                    settings, warning = receipt_settings.settings_state()
                self.assertIsNone(warning)
                self.assertNotIn('detail', settings['layout'])
                self.assertEqual(json.loads(path.read_text()), raw)  # Read-only compatibility.
