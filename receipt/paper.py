"""Approximate paper use from an already generated capture, never live data."""
from receipt.profile import COLUMNS

import base64
import math
import re
import struct


def estimate(pages, images=None):
    images = images or {}
    rows = []
    for name, text in pages.items():
        lines = 0
        image_mm = 0
        for line in text.splitlines():
            marker = re.fullmatch(r"\[\[RECEIPT_IMAGE_(\d+)\]\]", line.strip())
            if marker:
                try:
                    raw = base64.b64decode(
                        images.get(name, [])[int(marker[1])].split(",", 1)[1]
                    )
                    width, height = struct.unpack(">II", raw[16:24])
                    if not 0 < width <= 4096 or not 0 < height <= 100000:
                        raise ValueError()
                    image_mm += height / 8
                except (
                    IndexError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    struct.error,
                ):
                    image_mm += 50
            else:
                lines += max(1, math.ceil(len(line) / COLUMNS))
        cm = round((lines * 3.75 + image_mm + 15) / 10, 1)
        rows.append(dict(name=name, lines=lines, cm=cm))
    total = round(sum(r["cm"] for r in rows), 1)
    return dict(
        pages=rows,
        cm=total,
        year_metres=round(total * 365 / 100, 1),
        note=f"Approximate: {COLUMNS} columns, 3.75 mm per text line, image height at 203 dpi and 15 mm cutter allowance per page. Actual printer spacing and new live content can change this.",
    )
