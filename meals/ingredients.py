"""Combine compatible recipe quantities without guessing weight/count conversions."""
import re
from fractions import Fraction

PLURALS = {'onions': 'onion', 'carrots': 'carrot', 'peppers': 'pepper',
           'potatoes': 'potato', 'tomatoes': 'tomato', 'tortillas': 'tortilla',
           'lemons': 'lemon', 'limes': 'lime', 'cloves': 'clove', 'fillets': 'fillet',
           'breasts': 'breast', 'beans': 'bean', 'noodles': 'noodle'}
UNITS = {'kg': ('g', 1000), 'g': ('g', 1), 'l': ('ml', 1000), 'ml': ('ml', 1),
         'tsp': ('tsp', 1), 'tbsp': ('tsp', 3), 'tin': ('tin', 1), 'tins': ('tin', 1),
         'slice': ('slice', 1), 'slices': ('slice', 1), 'nest': ('nest', 1),
         'nests': ('nest', 1), 'handful': ('handful', 1), 'handfuls': ('handful', 1)}
QUANTITY = re.compile(r'^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*')


def parse(text):
    original = str(text).strip()
    value = original.casefold().replace('½', ' 1/2').replace('¼', ' 1/4').replace('¾', ' 3/4')
    match = QUANTITY.match(value.strip())
    if not match:
        return None
    raw = match.group(1)
    try:
        amount = sum((Fraction(part) for part in raw.split()), Fraction(0))
    except (ValueError, ZeroDivisionError):
        return None
    rest = value.strip()[match.end():].strip()
    unit, scale = 'count', 1
    unit_match = re.match(r'^(kg|ml|g|l|tsp|tbsp|tins?|slices?|nests?|handfuls?)\b\s*', rest)
    if unit_match:
        unit, scale = UNITS[unit_match.group(1)]
        rest = rest[unit_match.end():].strip()
        if rest.startswith('of '):
            rest = rest[3:]
    if not rest:
        return None
    identity = ' '.join(PLURALS.get(word, word) for word in rest.split())
    return amount * scale, unit, identity, rest


def number(amount):
    whole, remainder = divmod(amount.numerator, amount.denominator)
    if not remainder:
        return str(whole)
    fraction = f'{remainder}/{amount.denominator}'
    return f'{whole} {fraction}' if whole else fraction


def aggregate(items, *, for_shopping=False, pack_sizes=None):
    if for_shopping and pack_sizes is None:
        import json
        from config import DATA_DIR
        try:
            pack_sizes = json.loads((DATA_DIR / "pack_sizes.json").read_text())
        except (OSError, ValueError):
            pack_sizes = {}
    pack_sizes = pack_sizes or {}
    rows = {}
    for text in items:
        parsed = parse(text)
        if parsed is None:
            # Unmeasured quantities cannot be summed reliably; retain one wording.
            key = ('unmeasured', str(text).strip().casefold())
            rows.setdefault(key, str(text).strip())
            continue
        amount, unit, identity, label = parsed
        key = (unit, identity)
        if key in rows:
            rows[key][0] += amount
        else:
            rows[key] = [amount, unit, identity, label]
    output = []
    for row in rows.values():
        if isinstance(row, str):
            output.append(row)
            continue
        amount, unit, identity, label = row
        needed = amount
        note = ""
        if for_shopping:
            import math
            if unit in {'count', 'tin', 'nest', 'slice'}:
                amount = Fraction(math.ceil(amount))
            elif unit in {'g', 'ml'}:
                info = pack_sizes.get(label, pack_sizes.get(identity, {}))
                if info.get('unit') == unit:
                    packs = sorted(Fraction(str(size)) for size in info.get('packs', []) if float(size) > 0)
                    if packs:
                        amount = next((size for size in packs if size >= amount),
                                      Fraction(math.ceil(amount / packs[-1])) * packs[-1])
            if amount != needed:
                note = f" (need {number(needed)}{unit if unit in {'g', 'ml'} else ''})"
        if unit == 'count':
            words = identity.split()
            reverse = {singular: plural for plural, singular in PLURALS.items()}
            if amount > 1 and words[-1] in reverse:
                words[-1] = reverse[words[-1]]
            output.append(f'{number(amount)} {" ".join(words)}{note}')
        elif unit in {'g', 'ml'}:
            output.append(f'{number(amount)}{unit} {label}{note}')
        elif unit == 'tsp':
            chosen, quantity = ('tbsp', amount / 3) if amount >= 3 and amount % 3 == 0 else ('tsp', amount)
            output.append(f'{number(quantity)} {chosen} {label}')
        else:
            output.append(f'{number(amount)} {unit + ("s" if amount > 1 else "")} {label}{note}')
    return output
