"""Approximate paper and roll use from saved pages; never fetch live data."""
from receipt.profile import COLUMNS, ACTIVE
from receipt.paper_settings import load
import base64
import math
import re
import struct


def estimate(pages, images=None, *, settings=None):
    settings = load() if settings is None else settings
    images = images or {}
    rows = []
    for name, text in pages.items():
        if not text.strip():
            continue
        lines, image_mm = 0, 0
        for line in text.strip('\n').splitlines():
            marker = re.fullmatch(r'\[\[RECEIPT_IMAGE_(\d+)\]\]', line.strip())
            if marker:
                try:
                    raw = base64.b64decode(images.get(name, [])[int(marker[1])].split(',', 1)[1])
                    width, height = struct.unpack('>II', raw[16:24])
                    if not 0 < width <= 4096 or not 0 < height <= 100000:
                        raise ValueError()
                    scale = min(1, ACTIVE['printable_pixels'] / width)
                    image_mm += height * scale * 25.4 / ACTIVE['dpi']
                except (IndexError, ValueError, TypeError, AttributeError, struct.error):
                    image_mm += 50
            else:
                lines += max(1, math.ceil(len(line) / COLUMNS))
        cm = (lines * settings['line_mm'] + image_mm + settings['cutter_mm']) / 10
        rows.append(dict(name=name, lines=lines, cm=round(cm,1), raw_cm=cm))
    total = sum(row['raw_cm'] for row in rows)
    yearly = total / 100 * settings['prints_per_week'] * 365 / 7
    usable = settings['roll_length_m'] * (1 - settings['waste_percent']/100)
    rolls = yearly / usable
    nearest = round(rolls)
    required = math.ceil(nearest if math.isclose(rolls, nearest, rel_tol=0, abs_tol=1e-10) else rolls)
    return dict(pages=rows, cm=round(total,1), year_metres=round(yearly,1),
                rolls_per_year=round(rolls,2), rolls_required=required,
                replacements=max(0,required-1), days_per_roll=round(usable/(yearly/365),1) if yearly else None,
                roll_length_m=settings['roll_length_m'], usable_length_m=round(usable,1),
                prints_per_week=settings['prints_per_week'],
                note=f"Approximate: {COLUMNS} columns, {settings['line_mm']:g} mm per text line, {ACTIVE['dpi']} dpi and {settings['cutter_mm']:g} mm cutter allowance per page. Assumes these saved pages are printed {settings['prints_per_week']:g} times a week, with {settings['waste_percent']:g}% roll waste. Daily content, occasional pages and extra test prints change actual use.")
