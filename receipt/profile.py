"""Sizing shared by renderers and previews; restart applies geometry changes."""
from receipt.paper_settings import load, geometry
from textwrap import wrap

ACTIVE = load()
COLUMNS = ACTIVE['columns']
PRINTABLE_PIXELS = ACTIVE['printable_pixels']
FONT_A_DOTS = ACTIVE['font_dots']


def restart_required():
    return geometry(load()) != geometry(ACTIVE)


def printable_width(printer):
    try:
        width = printer.profile.profile_data['media']['width']['pixels']
    except (AttributeError, KeyError, TypeError):
        width = PRINTABLE_PIXELS
    if type(width) is not int or not 256 <= width <= 1024:
        width = PRINTABLE_PIXELS
    return width - width % 8


def fit_text(value, width=COLUMNS):
    """Wrap oversized legacy/body rows without changing rows that already fit."""
    rows = []
    for line in str(value).splitlines(keepends=True):
        ending = '\n' if line.endswith('\n') else ''
        text = line.rstrip('\r\n')
        if len(text) > width:
            if text and set(text) <= {'-', '='}:
                text = text[0] * width
            else:
                text = '\n'.join(wrap(text, width=width, replace_whitespace=False,
                                      break_long_words=True, break_on_hyphens=False))
        rows.append(text + ending)
    return ''.join(rows)


def web_context():
    return dict(receipt_columns=COLUMNS, receipt_pixels=PRINTABLE_PIXELS,
                receipt_paper_width=ACTIVE['paper_width_mm'], paper_profile_pending=restart_required())
