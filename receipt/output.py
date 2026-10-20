"""Small printer operations shared by pure renderers."""

from textwrap import wrap
from receipt.profile import COLUMNS
from receipt.text import printer_safe_text


def text(printer, value):
    printer.text(printer_safe_text(value))


def line(printer, character="-"):
    # Justification persists on hardware: a centred title must not centre the
    # shorter rule inside a printer's wider physical line (e.g. 48 vs 42 cells).
    printer.set(align="left")
    text(printer, ("-" if character == "=" else character) * COLUMNS + "\n")


def centre(printer, value):
    printer.set(align="center")
    text(printer, value + "\n")


def left(printer, value):
    printer.set(align="left")
    text(printer, value + "\n")


def wrapped(printer, value, width=COLUMNS):
    for row in wrap(value, width=width, break_long_words=False, break_on_hyphens=False):
        left(printer, row)


def heading(printer, value, *, write=left):
    """Centre semantic headings within the same column as body text and rules."""
    for row in wrap(printer_safe_text(value), width=COLUMNS) or [""]:
        write(printer, row.center(COLUMNS))
