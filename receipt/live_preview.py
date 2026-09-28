"""Live receipt rendering without printer hardware or persistent state changes."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import shutil


class VirtualPrinter:
    """Implements the small ESC/POS surface used by the live pipeline."""
    def __init__(self):
        self.profile = SimpleNamespace(profile_data={"media": {"width": {"pixels": 576}}})

    def hw(self, *args, **kwargs):
        pass

    def set(self, *args, **kwargs):
        pass

    def text(self, value):
        pass

    def image(self, value):
        pass

    def cut(self):
        pass


@contextmanager
def isolated_preview(*, pipeline=None, meal_planner=None, finance_receipt=None, subscriptions=None):
    """Keep planned meals, subscriptions, flags and trend snapshots unchanged."""
    if finance_receipt is None:
        from finance import receipt as finance_receipt
    if meal_planner is None:
        from meals import legacy_planner as meal_planner
    if pipeline is None:
        from services import live_pipeline as pipeline
    if subscriptions is None:
        from services import subscriptions as subscriptions

    original = {
        "usb": pipeline.Usb,
        "consume": pipeline.consume_one_shot,
        "pipeline_subscriptions": pipeline.SUBSCRIPTIONS_FILE,
        "subscriptions": subscriptions.SUBSCRIPTIONS_FILE,
        "plan_path": meal_planner.plan_path,
        "save_snapshot": finance_receipt.save_snapshot,
    }
    with TemporaryDirectory(prefix="receipt-preview-") as directory:
        scratch = Path(directory)
        temporary_subscriptions = scratch / "subscriptions.json"
        if original["subscriptions"].exists():
            shutil.copy2(original["subscriptions"], temporary_subscriptions)
        def isolated_plan_path(start):
            real = original["plan_path"](start)
            return real if real.exists() else scratch / real.name

        pipeline.Usb = VirtualPrinter
        pipeline.consume_one_shot = lambda *args, **kwargs: False
        pipeline.SUBSCRIPTIONS_FILE = temporary_subscriptions
        subscriptions.SUBSCRIPTIONS_FILE = temporary_subscriptions
        meal_planner.plan_path = isolated_plan_path
        finance_receipt.save_snapshot = lambda *args, **kwargs: None
        try:
            yield
        finally:
            pipeline.Usb = original["usb"]
            pipeline.consume_one_shot = original["consume"]
            pipeline.SUBSCRIPTIONS_FILE = original["pipeline_subscriptions"]
            subscriptions.SUBSCRIPTIONS_FILE = original["subscriptions"]
            meal_planner.plan_path = original["plan_path"]
            finance_receipt.save_snapshot = original["save_snapshot"]
