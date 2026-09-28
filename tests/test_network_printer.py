"""Network printing must be selected for the daily receipt without opening USB."""
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from receipt import printer as connection


class PrinterConnectionTests(unittest.TestCase):
    def setUp(self):
        self.network = []
        self.usb = []
        escpos = ModuleType("escpos")
        escpos.__path__ = []
        escpos_printer = ModuleType("escpos.printer")
        escpos_printer.Network = lambda *args, **kw: self.network.append((args, kw)) or object()
        escpos_printer.Usb = lambda *args, **kw: self.usb.append((args, kw)) or object()
        self.modules = patch.dict(sys.modules, {"escpos": escpos, "escpos.printer": escpos_printer})
        self.modules.start()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.modules.stop()

    def test_network_default_and_usb_override(self):
        connection.open_printer()
        self.assertEqual(self.network, [((connection.DEFAULT_NETWORK_HOST,),
                                        {"port": 9100, "timeout": 10})])
        self.assertFalse(self.usb)
        os.environ["RECEIPT_PRINTER_HOST"] = "203.0.113.5"
        connection.open_printer()
        self.assertEqual(self.network[-1][0], ("203.0.113.5",))
        os.environ["RECEIPT_PRINTER_CONNECTION"] = "usb"
        connection.open_printer()
        self.assertEqual(self.usb, [((0x0416, 0x5011), {})])

    def test_main_receipt_uses_network_factory_and_restores_pipeline(self):
        original_usb = object()
        pipeline = SimpleNamespace(Usb=original_usb)
        called = []
        def run_pipeline(**kwargs):
            called.append((pipeline.Usb(0x0416, 0x5011), kwargs))
        pipeline.run_live_pipeline = run_pipeline
        services = ModuleType("services")
        services.__path__ = []
        services.live_pipeline = pipeline
        with patch.dict(sys.modules, {"services": services, "services.live_pipeline": pipeline}):
            spec = importlib.util.spec_from_file_location(
                "daily_app_under_test", Path(__file__).resolve().parents[1] / "app.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.run_live(only_page="food")
        self.assertEqual(len(self.network), 1)
        self.assertEqual(called[0][1], {"force_finance": False, "only_page": "food"})
        self.assertIs(pipeline.Usb, original_usb)


if __name__ == "__main__":
    unittest.main()
