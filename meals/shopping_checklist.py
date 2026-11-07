"""Build local shopping lists and format them for a thermal receipt."""

import hashlib
import json
from textwrap import wrap

from meals.ingredients import aggregate, parse
from receipt.profile import COLUMNS
from receipt.text import printer_safe_text


def review(visits, scope):
    """Combine exact recipe quantities, without adding the rounded pack counts."""
    flags = {}
    ingredients = []
    for visit in visits:
        for item in visit["items"]:
            for line in item["requirements"]:
                ingredients.append(line)
                parsed = parse(line)
                key = (parsed[1], parsed[2]) if parsed else (None, line.casefold())
                flags[key] = flags.get(key, False) or item["pantry"]
    rows = []
    for line in aggregate(ingredients):
        parsed = parse(line)
        key = (parsed[1], parsed[2]) if parsed else (None, line.casefold())
        rows.append(
            dict(
                id=str(len(rows)),
                amount=line,
                pantry=flags.get(key, False),
                measured=bool(parsed and parsed[0] > 0 and parsed[1] != "handful"),
            )
        )
    fingerprint = hashlib.sha256(
        json.dumps([scope, rows], sort_keys=True).encode()
    ).hexdigest()
    return rows, fingerprint


def receipt_text(day, supplier, amounts, columns=COLUMNS):
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
    return "\n".join(rows) + "\n"
