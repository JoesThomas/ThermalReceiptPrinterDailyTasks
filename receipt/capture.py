"""Capture the printable text of a web-triggered receipt as it prints."""
from __future__ import annotations

import json
import base64
import binascii
import re
from datetime import datetime, timezone
from pathlib import Path

CAPTURE_FILE = Path(__file__).resolve().parent.parent / "data" / "last_web_receipt.json"
LIVE_PREVIEW_FILE = Path(__file__).resolve().parent.parent / "data" / "live_receipt_preview.json"
PAGE_NAMES = ("information", "actions", "food", "finance")
IMAGE_MARKER = re.compile(r"\[\[RECEIPT_IMAGE_(\d+)\]\]")


class RecordingPrinter:
    def __init__(self, printer):
        self.printer = printer
        self.lines = []
        self.images = []
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
        try:
            bitmap = args[0]
            position = bitmap.tell()
            bitmap.seek(0)
            data = bitmap.read()
            bitmap.seek(position)
            if len(data) > 512_000:
                raise ValueError("Image too large for preview")
            self.images.append("data:image/png;base64," + base64.b64encode(data).decode("ascii"))
            self.lines.append(f"[[RECEIPT_IMAGE_{len(self.images) - 1}]]\n")
        except (AttributeError, IndexError, OSError, ValueError):
            self.lines.append("[ PRINTED GRAPH / IMAGE ]\n")

    def cut(self, *args, **kwargs):
        self.printer.cut(*args, **kwargs)
        self.lines.append("\n--- CUT ---\n")

    def save(self, only_page=None, path=CAPTURE_FILE, replace=False):
        content = "".join(self.lines)
        sections = [part.strip("\n") for part in content.split("\n--- CUT ---\n") if part.strip()]
        captured_at = datetime.now(timezone.utc).isoformat()
        existing = None if replace else load_capture(path)
        pages = existing['pages'] if existing else {}
        page_times = existing['page_times'] if existing else {}
        page_images = existing['page_images'] if existing else {}

        def store_section(name, section):
            images = []
            def local_marker(match):
                number = int(match.group(1))
                if number >= len(self.images):
                    return "[ PRINTED GRAPH / IMAGE ]"
                images.append(self.images[number])
                return f"[[RECEIPT_IMAGE_{len(images) - 1}]]"
            pages[name] = IMAGE_MARKER.sub(local_marker, section)
            page_images[name] = images
            page_times[name] = captured_at

        if only_page is None:
            names = PAGE_NAMES[:3] + (("finance",) if len(sections) > 3 else ())
            for name, section in zip(names, sections):
                store_section(name, section)
        else:
            store_section(only_page, sections[0] if sections else "")
        path.parent.mkdir(parents=True, exist_ok=True)
        from receipt.freshness import snapshot
        from storage import write_json
        write_json(path, {"freshness": snapshot(), "page_times": page_times, "pages": pages,
                          "page_images": page_images})
        from receipt.archive import save as archive_save
        from receipt.freshness import snapshot
        fresh = {name: value for name, value in pages.items() if page_times.get(name) == captured_at}
        if fresh:
            try:
                archive_save(fresh, {name: page_images[name] for name in fresh}, captured_at,
                             "preview" if path == LIVE_PREVIEW_FILE else "printed", snapshot())
            except OSError:
                import logging
                logging.getLogger(__name__).warning("Receipt saved, but its archive copy could not be written.")


def load_capture(path=CAPTURE_FILE):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('pages'), dict):
            return None
        pages = {key: value for key, value in data['pages'].items() if key in PAGE_NAMES and isinstance(value, str)}
        raw_times = data.get('page_times', {})
        times = {key: value for key, value in raw_times.items() if key in pages and isinstance(value, str)} if isinstance(raw_times, dict) else {}
        raw_images = data.get('page_images', {})
        images = {key: value for key, value in raw_images.items() if key in pages and isinstance(value, list)} if isinstance(raw_images, dict) else {}
        raw_checks = data.get('freshness', {})
        checks = {key: value for key, value in raw_checks.items() if isinstance(value, dict) and isinstance(value.get('status'), str) and isinstance(value.get('checked_at'), str)} if isinstance(raw_checks, dict) else {}
        return dict(pages=pages, page_times=times, page_images=images, freshness=checks)
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def receipt_blocks(text, images=()):
    """Return escaped-by-template text and captured images in paper order."""
    result = []
    for position, piece in enumerate(IMAGE_MARKER.split(str(text))):
        if position % 2:
            index = int(piece)
            if index < len(images) and str(images[index]).startswith("data:image/png;base64,"):
                image = images[index]
                try:
                    header = base64.b64decode(image.split(",", 1)[1][:32], validate=True)
                    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
                        raise ValueError("Invalid PNG header")
                    width = int.from_bytes(header[16:20], "big")
                    width_percent = min(100, max(1, width * 100 / 576))
                except (ValueError, IndexError, binascii.Error):
                    width_percent = 100
                result.append({"image": image, "width_percent": width_percent})
            else:
                result.append({"text": "[ PRINTED GRAPH / IMAGE ]"})
        elif piece:
            result.append({"text": piece})
    return result
