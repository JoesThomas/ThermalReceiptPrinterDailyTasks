"""Format and spool a one-off note without placing it in the receipt archive."""
from pathlib import Path
import re
from textwrap import TextWrapper, wrap
from uuid import uuid4

from receipt.profile import COLUMNS
from receipt.text import printer_safe_text
from storage import PrivateStore, write_json, read_json_object

MAX_CHARS = 20_000
MAX_ALLOWED_CHARS = 100_000
# The character setting is the user-facing limit; wrapped lines must not impose
# an unexpected smaller limit, even when every character is on its own line.
MAX_LINES = MAX_ALLOWED_CHARS + 125
MAX_RENDERED_CHARS = MAX_ALLOWED_CHARS * 10
MAX_TITLE_CHARS = 120


def validate_limit(value):
    if type(value) is not int or not 1 <= value <= MAX_ALLOWED_CHARS:
        raise ValueError(f"Choose a character limit from 1 to {MAX_ALLOWED_CHARS:,}.")


def settings_store(root):
    def validate(value):
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("Invalid Quick Print settings.")
        validate_limit(value.get("max_chars"))

    return PrivateStore(
        Path(root) / "data" / "quick_print_settings.json",
        default=lambda: dict(version=1, max_chars=MAX_CHARS),
        validate=validate, max_bytes=1024,
    )


def length_advice(note):
    count = len(note.splitlines())
    if count > 80:
        return (
            f"This layout has {count:,} printed lines and will make a long receipt. "
            "Consider keeping only key points, splitting it into shorter notes, "
            "or reading the full text on screen."
        )
    return ""


def format_note(text, checklist=False, columns=COLUMNS, *, title="", max_chars=MAX_CHARS):
    validate_limit(max_chars)
    if len(text) > max_chars:
        raise ValueError(f"Use at most {max_chars:,} characters, or increase the limit in Quick Print settings.")
    if len(title) > MAX_TITLE_CHARS:
        raise ValueError(f"Use at most {MAX_TITLE_CHARS} characters for the title.")
    wrapper = TextWrapper(width=columns, replace_whitespace=False,
                          initial_indent="[ ] " if checklist else "",
                          subsequent_indent="    " if checklist else "")
    lines = []
    for raw in printer_safe_text(text).strip("\n").split("\n"):
        lines.extend(wrapper.wrap(raw.strip()) or [""])
    if not any(lines):
        raise ValueError("Enter some printable text.")
    heading = " ".join(printer_safe_text(title).split())
    if heading:
        lines = [line.center(columns).rstrip() for line in wrap(heading, width=columns)] + [""] + lines
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
    if (not isinstance(text, str) or not text or len(text) > MAX_RENDERED_CHARS
            or len(text.splitlines()) > MAX_LINES):
        raise ValueError("Quick Print note unavailable")
    printer = ContentPrinter(open_printer(initial_cut=False))
    try:
        printer.hw("init")
        printer.set(font="a", normal_textsize=True, align="left")
        printer.text(printer_safe_text(text))
        printer.cut()
    finally:
        printer.close()
