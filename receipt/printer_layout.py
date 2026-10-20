"""Physical-only text positioning, independent of raster margin side effects.

Keep saved content at 46 columns. On the 48-column Font A printer, add the
one-space inset only as text is sent to hardware. Native-centred headings
and full-width bitmaps retain their shared paper midpoint.
"""
from receipt.profile import COLUMNS, FONT_A_DOTS, printable_width


class ContentPrinter:
    def __init__(self, printer, columns=COLUMNS):
        self.printer = printer
        self.columns = columns
        self.align = 'left'
        self.line_start = True
        self.image_pending = False

    def __getattr__(self, name):
        return getattr(self.printer, name)

    def hw(self, command):
        self.printer.hw(command)
        if command == 'init':
            self.align, self.line_start, self.image_pending = 'left', True, False

    def set(self, *args, **kwargs):
        if kwargs.get('align'):
            self.align = kwargs['align']
        self.printer.set(*args, **kwargs)

    def _finish_image(self):
        pending = self.image_pending
        if pending:
            # Some compatible printers accept positioning only after an explicit
            # LF following GS v 0. Reuse the renderer's LF rather than add one.
            self.printer.text('\n')
            self.image_pending = False
            self.line_start = True
        return pending

    def text(self, value):
        value = str(value)
        if self._finish_image() and value.startswith('\n'):
            value = value[1:]
        if not value:
            return
        padding = max(0, (printable_width(self.printer) // FONT_A_DOTS - self.columns) // 2)
        rows = []
        for row in value.splitlines(keepends=True):
            if self.line_start and self.align == 'left' and row.strip():
                rows.append(' ' * padding)
            rows.append(row)
            self.line_start = row.endswith(('\n', '\r'))
        # Reassert justification after a raster boundary before sending text.
        self.printer.set(align=self.align)
        self.printer.text(''.join(rows))

    def image(self, *args, **kwargs):
        self._finish_image()
        self.printer.set(align='center')
        self.printer.image(*args, **kwargs)
        self.image_pending = True

    def cut(self, *args, **kwargs):
        self._finish_image()
        self.printer.cut(*args, **kwargs)
        self.line_start = True
