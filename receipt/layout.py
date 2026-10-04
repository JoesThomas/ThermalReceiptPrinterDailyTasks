"""Optional page ordering; unchanged order streams directly to the printer."""
from io import BytesIO

PAGES = ('information', 'actions', 'food', 'finance')
DEFAULT = {'order': list(PAGES), 'detail': 'detailed'}


def validate(value):
    if not isinstance(value, dict) or not isinstance(value.get('detail', 'detailed'), str) or value.get('detail', 'detailed') not in {'compact', 'detailed'}:
        raise ValueError('Choose compact or detailed receipts.')
    order = value.get('order', list(PAGES))
    if not isinstance(order, list) or len(order) != 4 or any(not isinstance(x, str) for x in order) or set(order) != set(PAGES):
        raise ValueError('Choose each receipt page once.')
    return {'order': order, 'detail': value.get('detail', 'detailed')}


class OrderedPrinter:
    """Buffer rendering operations only when a custom order requires it."""
    def __init__(self, target, order):
        self.target, self.order = target, order
        self.pages = {}
        self.current = None

    def __getattr__(self, name):
        return getattr(self.target, name)

    def begin(self, name):
        self.current = name
        self.pages[name] = []

    def _record(self, name, args, kwargs):
        if self.current is None:
            raise ValueError('Receipt page has not started.')
        self.pages[self.current].append((name, args, kwargs))

    def text(self, *args, **kwargs): self._record('text', args, kwargs)
    def set(self, *args, **kwargs): self._record('set', args, kwargs)
    def cut(self, *args, **kwargs): self._record('cut', args, kwargs)

    def image(self, value, *args, **kwargs):
        position = value.tell()
        value.seek(0)
        content = value.read()
        value.seek(position)
        self._record('image', (content, *args), kwargs)

    def flush(self):
        self.target.capture_order = [name for name in self.order if name in self.pages]
        for name in self.target.capture_order:
            self.target.set(align='left', bold=False)
            for method, args, kwargs in self.pages[name]:
                if method == 'image': args = (BytesIO(args[0]), *args[1:])
                getattr(self.target, method)(*args, **kwargs)
        self.pages.clear()


def begin(printer, name):
    if isinstance(printer, OrderedPrinter): printer.begin(name)


def checked_lines(names):
    from receipt.freshness import snapshot
    from receipt.local_time import uk_receipt_time
    result = []
    for name, check in snapshot().items():
        if name in names:
            stamp = uk_receipt_time(check.get('source_checked_at') or check['checked_at'])
            result.append(f"{name}: {check['status']} {stamp}")
    return result
