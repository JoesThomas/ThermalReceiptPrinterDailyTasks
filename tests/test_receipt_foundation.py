import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from receipt.build import build
from receipt.capture import RecordingPrinter
from receipt.live_preview import VirtualPrinter
from receipt import archive
from receipt.changes import compare
from services import public_sources, source_cache
from web_control import diagnostics


class ReceiptFoundationTests(unittest.TestCase):
    def test_preview_and_print_build_identical_operations_then_send(self):
        pipeline = SimpleNamespace(Usb=object())
        original = pipeline.Usb
        def run(**kwargs):
            printer = pipeline.Usb(1, 2)
            printer.hw('init'); printer.text('Same receipt\n'); printer.cut()
        device = Mock()
        with patch.object(RecordingPrinter, 'save') as save:
            preview = build(pipeline, run, VirtualPrinter, only_page='information')
            physical = build(pipeline, run, lambda: device, only_page='information')
            self.assertEqual(preview.lines, physical.lines)
            self.assertEqual(preview.operations, physical.operations)
            device.text.assert_not_called()
            physical.send()
            device.text.assert_called_once_with('Same receipt\n')
            self.assertEqual(save.call_count, 2)
        self.assertIs(pipeline.Usb, original)

    def test_public_source_uses_stale_cache_then_expires(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache, 'FILE', Path(folder)/'cache.json'), patch('receipt.freshness.mark') as mark, patch.object(source_cache.time, 'time', return_value=1000):
            value = public_sources.cached('UK news', 'https://example.test', 3, lambda: [{'headline':'Example'}])
            source_cache.refresh()
            def fail(): raise TimeoutError()
            self.assertEqual(public_sources.cached('UK news','https://example.test',3,fail), value)
            self.assertEqual(mark.call_args.args[1], 'cached after error')
            with patch.object(source_cache.time,'time',return_value=5000), self.assertRaises(TimeoutError):
                public_sources.cached('UK news','https://example.test',3,fail)

    def test_download_size_limit_and_response_cleanup(self):
        response = Mock()
        response.iter_content.return_value = [b'x' * 2_000_001]
        with patch('services.api_health.observed_request',return_value=response), self.assertRaises(ValueError):
            public_sources.download('Weather','https://example.test')
        response.close.assert_called_once()

    def test_partial_receipts_compare_each_page_without_losing_baseline(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(archive,'DIRECTORY',Path(folder)):
            archive.save({'actions':'Old task\n','information':'Old news'}, {}, '2026-10-01T12:00:00+00:00','preview',{})
            archive.save({'information':'New news'}, {}, '2026-10-02T12:00:00+00:00','preview',{})
            identifier = archive.save({'actions':'New task\n'}, {}, '2026-10-03T12:00:00+00:00','preview',{})
            changes = compare(archive.load(identifier))[0]
            self.assertEqual(changes['added'], ['New task'])
            self.assertEqual(changes['removed'], ['Old task'])

    def test_diagnostic_download_omits_personal_fields_and_raw_errors(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(diagnostics,'ROOT',Path(folder)), patch.object(diagnostics.api_health,'load',return_value={'services':{'Weather':{'status':'failed','reason':'timeout','error':'SECRET','url':'SECRET'}}}), patch.object(diagnostics,'load_capture',return_value=None), patch.object(diagnostics.source_cache,'timings',return_value=[]):
            (Path(folder)/'data').mkdir()
            (Path(folder)/'data'/'web_print_status.json').write_text(json.dumps({'state':'failed','stage':'SECRET','error':'SECRET'}))
            text = json.dumps(diagnostics.export())
            self.assertNotIn('SECRET',text)
            self.assertIn('timeout',text)
