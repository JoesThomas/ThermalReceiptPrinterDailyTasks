from __future__ import annotations

from services import live_pipeline
from services.live_pipeline import run_live_pipeline


def run_live(*, finance_requested=False, only_page=None, live_preview=False, selected_pages=None):
    """Generate and save once; optionally send the same buffered operations."""
    from receipt.freshness import reset
    from receipt.build import build
    from receipt.preview_progress import report
    reset()
    if live_preview:
        from receipt.live_preview import isolated_preview, VirtualPrinter
        with isolated_preview():
            build(live_pipeline, run_live_pipeline, VirtualPrinter,
                  finance_requested=finance_requested, only_page=only_page, selected_pages=selected_pages)
        report('Preview saved', 5, 5)
        return

    from receipt.printer import open_printer, DeferredPhysicalPrinter
    recorder = build(live_pipeline, run_live_pipeline,
                     lambda: DeferredPhysicalPrinter(open_printer),
                     finance_requested=finance_requested, only_page=only_page, selected_pages=selected_pages)
    if recorder is not None:
        try:
            report('Sending receipt to printer', 4, 5)
            recorder.printer.open()
            recorder.send()
            recorder.save(only_page)
            print('Receipt sent to printer; paper output not confirmed.')
            report('Receipt sent to printer', 5, 5)
        except Exception as error:
            from receipt.printer import PrinterConnectionError
            if isinstance(error, PrinterConnectionError):
                report('Printer unavailable; generated preview saved', 4, 5)
                raise PrinterConnectionError(str(error) + ' The generated copy is saved in Receipt preview; reconnect and choose Print saved preview.') from None
            raise
        finally:
            recorder.printer.close()
