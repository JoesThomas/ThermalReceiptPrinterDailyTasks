"""Capture the printable text of a web-triggered receipt as it prints."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CAPTURE_FILE = Path(__file__).resolve().parent.parent / "data" / "last_web_receipt.json"
PAGE_NAMES = ("information", "actions", "food", "finance")


class RecordingPrinter:
    def __init__(self, printer):
        self.printer = printer
        self.lines = []
        self.align = "left"

    def __getattr__(self, name):
        return getattr(self.printer, name)

    def set(self, *args, **kwargs):
        self.printer.set(*args, **kwargs)
        if kwargs.get("align"):
            self.align = kwargs["align"]

    def text(self, value):
        self.printer.text(value)
        value = str(value)
        if self.align == "center":
            value = "".join(line.rstrip("\r\n").center(42) + ("\n" if line.endswith("\n") else "")
                            for line in value.splitlines(keepends=True))
        self.lines.append(value)

    def image(self, *args, **kwargs):
        self.printer.image(*args, **kwargs)
        self.lines.append("[ PRINTED GRAPH / IMAGE ]\n")

    def cut(self, *args, **kwargs):
        self.printer.cut(*args, **kwargs)
        self.lines.append("\n--- CUT ---\n")

    def save(self, only_page=None, path=CAPTURE_FILE):
        content = "".join(self.lines)
        sections = [part.strip("\n") for part in content.split("\n--- CUT ---\n") if part.strip()]
        captured_at = datetime.now(timezone.utc).isoformat()
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            pages = existing.get("pages", {}) if isinstance(existing, dict) else {}
            page_times = existing.get("page_times", {}) if isinstance(existing, dict) else {}
            if not isinstance(pages, dict) or not isinstance(page_times, dict):
                pages, page_times = {}, {}
        except (OSError, ValueError):
            pages, page_times = {}, {}
        if only_page is None:
            names = PAGE_NAMES[:3] + (("finance",) if len(sections) > 3 else ())
            for name, section in zip(names, sections):
                pages[name] = section
                page_times[name] = captured_at
        else:
            pages[only_page] = sections[0] if sections else ""
            page_times[only_page] = captured_at
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"page_times": page_times, "pages": pages},
                                        ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def load_capture(path=CAPTURE_FILE):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = data.get("pages", {})
        if not isinstance(pages, dict):
            return None
        return {"page_times": data.get("page_times", {}),
                "pages": {key: str(value) for key, value in pages.items() if key in PAGE_NAMES}}
    except (OSError, ValueError, TypeError):
        return None
