"""One sizing profile shared by rendering, capture and web previews."""
from contextlib import contextmanager

COLUMNS = 42
PRINTABLE_PIXELS = 576


def printable_width(printer):
    try:
        width = printer.profile.profile_data["media"]["width"]["pixels"]
    except (AttributeError, KeyError, TypeError):
        width = PRINTABLE_PIXELS
    if type(width) is not int or not 256 <= width <= 1024:
        width = PRINTABLE_PIXELS
    return width - width % 8


def web_context():
    return {"receipt_columns": COLUMNS, "receipt_pixels": PRINTABLE_PIXELS}

# Font A uses 12 horizontal dots per standard-width character on the 203dpi
# 80mm printer. Centre the existing 42-column block inside its 576-dot line.
FONT_A_DOTS = 12
TEXT_PIXELS = COLUMNS * FONT_A_DOTS


def _area(left, width):
    return b'\x1dL' + left.to_bytes(2, 'little') + b'\x1dW' + width.to_bytes(2, 'little')


def centre_text_area(printer):
    """Set native margins after ESC @, without adding spaces to saved text."""
    physical = printable_width(printer)
    width = min(TEXT_PIXELS, physical)
    # GS P sets motion units to one dot at this printer's 203dpi resolution.
    printer._raw(b'\x1dP\xcb\xcb' + _area((physical - width) // 2, width))
    printer.centered_text_area = True


@contextmanager
def full_width_image(printer):
    """Keep existing full-width graphs centred, then restore the text margins."""
    enabled = getattr(printer, 'centered_text_area', False) is True
    if enabled:
        physical = printable_width(printer)
        printer._raw(_area(0, physical))
    try:
        yield
    finally:
        if enabled:
            width = min(TEXT_PIXELS, physical)
            printer._raw(_area((physical - width) // 2, width))
