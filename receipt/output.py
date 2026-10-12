"""Small printer operations shared by pure renderers."""

from textwrap import wrap
from receipt.profile import COLUMNS
from receipt.text import printer_safe_text


def text(printer, value):
    printer.text(printer_safe_text(value))


def line(printer, character="-"):
    text(printer, ("-" if character == "=" else character) * COLUMNS + "\n")


def centre(printer, value):
    printer.set(align="center")
    text(printer, value + "\n")


def left(printer, value):
    printer.set(align="left")
    text(printer, value + "\n")


def wrapped(printer, value, width=40):
    for row in wrap(value, width=width, break_long_words=False, break_on_hyphens=False):
        left(printer, row)
