from __future__ import annotations

import os

from services import live_pipeline
from services.live_pipeline import run_live_pipeline


def run_live(
    *,
    finance_requested: bool = False,
    only_page: str | None = None,
    live_preview: bool = False,
) -> None:
    """
    Run the live receipt pipeline.

    The existing pipeline still determines finance requests from the configured
    trigger/source. The keyword is retained so main.py has a stable modular API
    while individual collectors continue to be separated further.
    """
    if live_preview:
        from receipt.capture import LIVE_PREVIEW_FILE, RecordingPrinter
        from receipt.live_preview import isolated_preview
        recorder = None
        with isolated_preview():
            original_usb = live_pipeline.Usb
            def virtual_capture(*args, **kwargs):
                nonlocal recorder
                recorder = RecordingPrinter(original_usb(*args, **kwargs))
                return recorder
            live_pipeline.Usb = virtual_capture
            try:
                run_live_pipeline(force_finance=finance_requested, only_page=only_page)
            finally:
                live_pipeline.Usb = original_usb
        if recorder is not None:
            recorder.save(only_page, path=LIVE_PREVIEW_FILE, replace=True)
        return

    if os.environ.get("RECEIPT_WEB_CAPTURE") != "1":
        from receipt.printer import open_printer
        original_usb = live_pipeline.Usb
        live_pipeline.Usb = lambda *args, **kwargs: open_printer()
        try:
            run_live_pipeline(force_finance=finance_requested, only_page=only_page)
        finally:
            live_pipeline.Usb = original_usb
        return

    from receipt.capture import RecordingPrinter
    from receipt.printer import open_printer
    original_usb = live_pipeline.Usb
    recorder = None

    def recording_usb(*args, **kwargs):
        nonlocal recorder
        recorder = RecordingPrinter(open_printer())
        return recorder

    live_pipeline.Usb = recording_usb
    try:
        run_live_pipeline(force_finance=finance_requested, only_page=only_page)
    finally:
        live_pipeline.Usb = original_usb
    if recorder is not None:
        recorder.save(only_page)
