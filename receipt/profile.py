"""One sizing profile shared by rendering, capture and web previews."""

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
