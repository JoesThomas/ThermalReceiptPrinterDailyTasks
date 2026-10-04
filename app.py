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
    from receipt.freshness import reset
    reset()
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
        from receipt.preview_progress import report as preview_progress
        preview_progress("Preview saved", 5, 5)
        return

    from receipt.capture import RecordingPrinter
    from receipt.printer import open_printer, DeferredPhysicalPrinter
    original_usb = live_pipeline.Usb
    recorder = None

    def recording_usb(*args, **kwargs):
        nonlocal recorder
        recorder = RecordingPrinter(DeferredPhysicalPrinter(open_printer), defer=True)
        return recorder

    live_pipeline.Usb = recording_usb
    try:
        run_live_pipeline(force_finance=finance_requested, only_page=only_page)
    except Exception:
        if recorder is not None:
            recorder.printer.close()
        raise
    finally:
        live_pipeline.Usb = original_usb
    if recorder is not None:
        try:
            from receipt.preview_progress import report as print_progress
            print_progress("Sending receipt to printer", 4, 5)
            recorder.printer.open()
            recorder.send()
            recorder.save(only_page)
            print("Receipt sent to printer; paper output not confirmed.")
            print_progress("Receipt sent to printer", 5, 5)
        finally:
            recorder.printer.close()
