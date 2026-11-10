"""Build local shopping lists and format them for a thermal receipt."""

import hashlib
import json
from textwrap import wrap

from meals.ingredients import load_pack_sizes, shopping_amount
from receipt.profile import COLUMNS
from receipt.text import printer_safe_text


def review(visits, scope):
    """Combine exact recipe quantities, without adding the rounded pack counts."""
    grouped = {}
    for visit in visits:
        for item in visit["items"]:
            entry = grouped.setdefault(item["key"], dict(lines=[], pantry=False, whole_chicken=False))
            entry["lines"].extend(item["requirements"])
            entry["pantry"] |= item["pantry"]
            entry["whole_chicken"] |= item["whole_chicken"]
    pack_sizes = load_pack_sizes() if grouped else {}
    rows = [
        dict(
            id=str(index),
            key=key,
            amount=shopping_amount(key, entry["lines"], pack_sizes=pack_sizes),
            pantry=entry["pantry"],
            whole_chicken=entry["whole_chicken"],
        )
        for index, (key, entry) in enumerate(sorted(grouped.items()))
    ]
    fingerprint = hashlib.sha256(
        json.dumps([scope, rows], sort_keys=True).encode()
    ).hexdigest()
    return rows, fingerprint


def receipt_text(day, supplier, amounts, columns=COLUMNS, *, chicken_size=None):
    title = (
        f"{supplier.upper()} SHOPPING LIST" if supplier else "SUPERMARKET SHOPPING LIST"
    )
    rows = ["-" * columns]
    rows.extend(line.center(columns) for line in wrap(title, width=columns))
    rows.extend([day.strftime("%a %d %b %Y").center(columns), "-" * columns])
    for amount in amounts:
        cleaned = " ".join(printer_safe_text(amount).split())
        for index, line in enumerate(wrap(cleaned, width=columns - 4)):
            rows.append(("[ ] " if index == 0 else "    ") + line)
    if chicken_size:
        rows.extend(wrap(
            f"Whole-bird option: about {chicken_size['size']} for weighed cuts. Check yield.",
            width=columns,
        ))
    return "\n".join(rows) + "\n"
