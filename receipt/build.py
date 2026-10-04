"""One buffered generation path shared by live previews and physical printing."""
from receipt.capture import RecordingPrinter


def build(pipeline, run, factory, *, finance_requested=False, only_page=None, selected_pages=None):
    if selected_pages is not None:
        from receipt.selection import validate
        validate(selected_pages)
        if only_page is not None: raise ValueError("Use selected sections or one page, not both.")
    original = pipeline.Usb
    recorder = None

    def capture(*args, **kwargs):
        nonlocal recorder
        recorder = RecordingPrinter(factory(), defer=True)
        return recorder

    pipeline.Usb = capture
    try:
        options={"force_finance":finance_requested,"only_page":only_page}
        if selected_pages is not None: options["selected_pages"]=selected_pages
        run(**options)
        if recorder is not None:
            from receipt.capture import LIVE_PREVIEW_FILE
            recorder.save(only_page, path=LIVE_PREVIEW_FILE, replace=True)
        return recorder
    except Exception:
        if recorder is not None:
            close = getattr(recorder.printer, 'close', None)
            if close: close()
        raise
    finally:
        pipeline.Usb = original
