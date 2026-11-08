"""Format and spool a one-off note without placing it in the receipt archive."""
from pathlib import Path
import re
from textwrap import TextWrapper
from uuid import uuid4

from receipt.profile import COLUMNS
from receipt.text import printer_safe_text
from storage import write_json, read_json_object

MAX_CHARS = 2000
MAX_LINES = 80


def format_note(text, checklist=False, columns=COLUMNS):
    if len(text) > MAX_CHARS:
        raise ValueError("Use at most 2,000 characters.")
    wrapper = TextWrapper(width=columns, replace_whitespace=False,
                          initial_indent="[ ] " if checklist else "",
                          subsequent_indent="    " if checklist else "")
    lines = []
    for raw in printer_safe_text(text).strip("\n").split("\n"):
        lines.extend(wrapper.wrap(raw.strip()) or [""])
    if not any(lines):
        raise ValueError("Enter some printable text.")
    if len(lines) > MAX_LINES:
        raise ValueError("The note would print more than 80 lines. Shorten it before printing.")
    return "\n".join(lines) + "\n"


def path_for(root, key):
    if not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("Invalid note job")
    return Path(root) / "data" / "quick_notes" / (key + ".json")


def spool(root, text):
    key = uuid4().hex
    path = path_for(root, key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(path, {"text": text})
    return key


def send(root, key):
    from receipt.printer import open_printer
    from receipt.printer_layout import ContentPrinter

    path = path_for(root, key)
    text = read_json_object(path).get("text")
    path.unlink(missing_ok=True)
    if not isinstance(text, str) or not text or len(text.splitlines()) > MAX_LINES:
        raise ValueError("Quick Print note unavailable")
    printer = ContentPrinter(open_printer(initial_cut=False))
    try:
        printer.hw("init")
        printer.set(font="a", normal_textsize=True, align="left")
        printer.text(printer_safe_text(text))
        printer.cut()
    finally:
        printer.close()
