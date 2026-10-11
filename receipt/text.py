"""Shared conservative text cleaning for ESC/POS printers."""

import re
import unicodedata


def printer_safe_text(text):
    """Make text conservative for an ESC/POS printer while preserving £."""
    if text is None:
        return ""

    text = str(text)
    if text.isascii() and text.isprintable():
        return text

    replacements = {
        "\ufeff": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2022": "-",
        "\u00b7": "-",
        "\u00ae": "(R)",
        "\u00a9": "(C)",
        "\u2122": "(TM)",
        "\u20ac": "EUR",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2191": "^",
        "\u2193": "v",
        "\u00b0": " DEG ",
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    text = re.sub(
        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])",
        "",
        text,
    )

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")

    text = "".join(ch for ch in text if ch == "\n" or 32 <= ord(ch) <= 126 or ch == "£")

    return text
