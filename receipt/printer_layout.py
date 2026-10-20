"""Physical-only text positioning, independent of raster margin side effects.

Keep saved content at the configured column width. On the default 48-column
Font A printer, add the one-space inset only as text is sent to hardware. Native-centred headings
and full-width bitmaps retain their shared paper midpoint.
"""
from receipt.profile import COLUMNS, FONT_A_DOTS, printable_width, fit_text
import re


class ContentPrinter:
    def __init__(self, printer, columns=COLUMNS):
        self.printer = printer
        self.columns = columns
        self.align = 'left'
        self.line_start = True
        self.image_pending = False
        self.page_start = True

    def __getattr__(self, name):
        return getattr(self.printer, name)

    def hw(self, command):
        self.printer.hw(command)
        if command == 'init':
            self.align, self.line_start, self.image_pending = 'left', True, False
            self.page_start = True

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
        value = fit_text(value, self.columns)
        if self._finish_image() and value.startswith('\n'):
            value = value[1:]
        if self.page_start:
            value = re.sub(r'^(?:[ \t]*\r?\n)+', '', value)
        if not value:
            return
        self.page_start = False
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
        from PIL import Image
        from io import BytesIO
        if args and hasattr(args[0], 'read'):
            source = args[0]
            position = source.tell()
            source.seek(0)
            bitmap = Image.open(source)
            width = printable_width(self.printer)
            if bitmap.width > width:
                bitmap = bitmap.resize((width, round(bitmap.height * width / bitmap.width)))
                buffer = BytesIO()
                bitmap.save(buffer, format='PNG')
                buffer.seek(0)
                args = (buffer, *args[1:])
            source.seek(position)
        self.printer.image(*args, **kwargs)
        self.image_pending = True
        self.page_start = False

    def cut(self, *args, **kwargs):
        self._finish_image()
        if not self.line_start:
            self.printer.text('\n')
        profile = getattr(self.printer, 'profile', None)
        supports = getattr(profile, 'supports', None)
        raw = getattr(self.printer, '_raw', None)
        # GS V Function B advances the final print line to the cutter, with no
        # extra feed. Preserve full/partial support and explicit caller options.
        shape = None
        if callable(supports):
            if supports('paperFullCut') is True:
                shape = 65
            elif supports('paperPartCut') is True:
                shape = 66
        if not args and not kwargs and callable(raw) and shape is not None:
            raw(b'\x1dV' + bytes((shape, 0)))
        else:
            self.printer.cut(*args, **kwargs)
        self.line_start = True
        self.page_start = True
