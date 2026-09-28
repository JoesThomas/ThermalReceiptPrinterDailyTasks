"""The live receipt must not use hardware or change the print state."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from receipt.capture import RecordingPrinter, load_capture, receipt_blocks
from receipt.live_preview import VirtualPrinter, isolated_preview


class LivePreviewTests(unittest.TestCase):
    def test_isolation_redirects_writes_and_restores_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subscription_file = root / "subscriptions.json"
            subscription_file.write_text('{"monthly": []}', encoding="utf-8")
            plan_file = root / "planned.json"
            printer_type = object()
            def consume(*args):
                return True
            def snapshot(*args):
                raise AssertionError("Financial history changed")
            def path(start):
                return plan_file
            pipeline = SimpleNamespace(Usb=printer_type, consume_one_shot=consume,
                                       SUBSCRIPTIONS_FILE=subscription_file)
            subscriptions = SimpleNamespace(SUBSCRIPTIONS_FILE=subscription_file)
            meal_planner = SimpleNamespace(plan_path=path)
            finance_receipt = SimpleNamespace(save_snapshot=snapshot)
            with isolated_preview(pipeline=pipeline, subscriptions=subscriptions,
                                  meal_planner=meal_planner, finance_receipt=finance_receipt):
                self.assertIs(pipeline.Usb, VirtualPrinter)
                self.assertFalse(pipeline.consume_one_shot(None))
                self.assertNotEqual(subscriptions.SUBSCRIPTIONS_FILE, subscription_file)
                self.assertEqual(subscriptions.SUBSCRIPTIONS_FILE.read_text(), '{"monthly": []}')
                subscriptions.SUBSCRIPTIONS_FILE.write_text('changed', encoding='utf-8')
                self.assertNotEqual(meal_planner.plan_path(None), plan_file)
                finance_receipt.save_snapshot({})
            self.assertIs(pipeline.Usb, printer_type)
            self.assertIs(pipeline.consume_one_shot, consume)
            self.assertIs(subscriptions.SUBSCRIPTIONS_FILE, subscription_file)
            self.assertIs(meal_planner.plan_path, path)
            self.assertIs(finance_receipt.save_snapshot, snapshot)
            self.assertEqual(subscription_file.read_text(), '{"monthly": []}')

    def test_recorded_image_and_paper_pages_are_saved_without_printing(self):
        from io import BytesIO
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "preview.json"
            recorder = RecordingPrinter(VirtualPrinter())
            recorder.text("Today's news\n")
            recorder.image(BytesIO(b"\x89PNG\r\n\x1a\n"))
            recorder.cut()
            recorder.text("Actions\n")
            recorder.cut()
            recorder.text("Food\n")
            recorder.cut()
            recorder.save(path=file, replace=True)
            data = load_capture(file)
            self.assertEqual(list(data["pages"]), ["information", "actions", "food"])
            blocks = receipt_blocks(data["pages"]["information"], data["page_images"]["information"])
            self.assertTrue(any(block.get("image", "").startswith("data:image/png;base64,") for block in blocks))
            self.assertEqual(receipt_blocks("123"), [{"text": "123"}])
            self.assertEqual(json.loads(file.read_text())["page_times"].keys(), data["page_times"].keys())


if __name__ == "__main__":
    unittest.main()
