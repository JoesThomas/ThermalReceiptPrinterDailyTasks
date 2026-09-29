"""The To buy wish list is local and prints only when requested."""
import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from receipt_settings import load_receipt_settings, one_shot_requested, consume_one_shot
from web_control import to_buy

ROOT = Path(__file__).resolve().parents[1]


class ToBuyTests(unittest.TestCase):
    def test_default_items_and_local_edits(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(to_buy, 'TO_BUY_FILE', Path(directory) / 'to_buy.json'):
            self.assertEqual(to_buy.load_to_buy(), [])
            self.assertEqual(to_buy.save_to_buy('Example item\n\nNew item\n'),
                             ['Example item', 'New item'])
            self.assertEqual(to_buy.load_to_buy(), ['Example item', 'New item'])
            with self.assertRaises(ValueError):
                to_buy.save_to_buy('x' * 161)
            self.assertEqual(to_buy.load_to_buy(), ['Example item', 'New item'])

    def test_one_shot_clears_after_successful_print(self):
        import receipt_settings
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(receipt_settings, 'SETTINGS_FILE', Path(directory) / 'settings.json'):
            settings = load_receipt_settings()
            settings['one_shot']['to_buy'] = True
            self.assertTrue(one_shot_requested(settings, 'to_buy'))
            self.assertTrue(consume_one_shot(settings, 'to_buy'))
            self.assertFalse(load_receipt_settings()['one_shot']['to_buy'])

    def test_receipt_heading_and_printer_safe_wrapping(self):
        source = ast.parse((ROOT / 'services/live_pipeline.py').read_text(encoding='utf-8'))
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'print_to_buy')
        lines = []
        printer = SimpleNamespace(set=lambda **kw: None)
        namespace = {
            'print_line': lambda *args: None,
            'centre': lambda printer, text: lines.append(text),
            'left': lambda printer, text: lines.append(text),
            'print_wrapped': lambda printer, text, width: lines.append((text, width)),
            'printer_safe_text': lambda text: text.replace('®', '(R)'),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'live_pipeline.py', 'exec'), namespace)
        namespace['print_to_buy'](printer, ["An item ®", 'Example item'])
        self.assertEqual(lines, ['TO BUY', ("[ ] An item (R)", 40),
                                 ('[ ] Example item', 40)])


if __name__ == '__main__':
    unittest.main()
