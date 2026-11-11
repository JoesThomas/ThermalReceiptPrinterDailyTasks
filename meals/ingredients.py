"""Combine compatible recipe quantities without guessing weight/count conversions."""
import re
from fractions import Fraction
from functools import lru_cache
import json
import math

PLURALS = {'onions': 'onion', 'carrots': 'carrot', 'peppers': 'pepper',
           'potatoes': 'potato', 'tomatoes': 'tomato', 'tortillas': 'tortilla',
           'lemons': 'lemon', 'limes': 'lime', 'cloves': 'clove', 'fillets': 'fillet',
           'breasts': 'breast', 'thighs': 'thigh', 'chickens': 'chicken', 'beans': 'bean', 'noodles': 'noodle',
           'apples': 'apple', 'bananas': 'banana', 'avocados': 'avocado',
           'cucumbers': 'cucumber', 'mushrooms': 'mushroom', 'courgettes': 'courgette',
           'pizzas': 'pizza', 'fingers': 'finger', 'kievs': 'kiev',
           'nuggets': 'nugget', 'goujons': 'goujon', 'fishcakes': 'fishcake',
           'sausages': 'sausage'}
SINGULAR_TO_PLURAL = {singular: plural for plural, singular in PLURALS.items()}
UNITS = {'kg': ('g', 1000), 'g': ('g', 1), 'l': ('ml', 1000), 'ml': ('ml', 1),
         'tsp': ('tsp', 1), 'tbsp': ('tsp', 3), 'tin': ('tin', 1), 'tins': ('tin', 1),
         'slice': ('slice', 1), 'slices': ('slice', 1), 'nest': ('nest', 1),
         'nests': ('nest', 1), 'handful': ('handful', 1), 'handfuls': ('handful', 1)}
QUANTITY = re.compile(r'^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*')
UNMEASURED_SCALE = re.compile(r' \(unmeasured; scale for \d+(?:\.\d+)?x\)$')
LEAF_CHOICES = {
    'leafy greens': 'baby spinach (suggested)',
    'salad leaves': 'mixed salad leaves',
    'spinach': 'spinach',
    'baby spinach': 'baby spinach',
    'mixed salad leaves': 'mixed salad leaves',
    'lettuce': 'lettuce',
}
LEAF_HANDFUL_GRAMS = 25  # Shopping estimate, not a recipe measurement.


def leaf_shopping_lines(key, lines):
    """Estimate only explicit handfuls, retaining weights and unknown amounts."""
    if key not in LEAF_CHOICES:
        return lines, False
    converted = []
    estimated = False
    for line in lines:
        parsed = parse(line)
        handfuls = None
        if parsed and parsed[1] == 'handful':
            handfuls = parsed[0]
        elif not parsed:
            raw = ' '.join(str(line).casefold().split())
            if UNMEASURED_SCALE.sub('', raw).startswith('handful of '):
                scale = re.search(r' \(unmeasured; scale for (\d+(?:\.\d+)?)x\)$', raw)
                handfuls = Fraction(scale.group(1)) if scale else Fraction(1)
        if handfuls is not None and handfuls > 0:
            converted.append(f'{number(handfuls * LEAF_HANDFUL_GRAMS)}g {key}')
            estimated = True
        else:
            converted.append(line)
    return converted, estimated


def parse(text):
    original = str(text).strip()
    return _cached_parse(original) if len(original) <= 256 else _parse(original)


def _parse(original):
    value = original.casefold().replace('½', ' 1/2').replace('¼', ' 1/4').replace('¾', ' 3/4')
    match = QUANTITY.match(value.strip())
    if not match:
        return None
    raw = match.group(1)
    try:
        parts = raw.split()
        amount = Fraction(parts[0])
        if len(parts) == 2:
            amount += Fraction(parts[1])
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
    return amount if scale == 1 else amount * scale, unit, identity, rest


_cached_parse = lru_cache(maxsize=1024)(_parse)


def shopping_key(line):
    parsed = parse(line)
    if parsed:
        return ('tinned ' if parsed[1] == 'tin' else '') + parsed[2]
    name = UNMEASURED_SCALE.sub('', ' '.join(str(line).casefold().split()))
    name = name.removeprefix('handful of ')
    return ' '.join(PLURALS.get(word, word) for word in name.split())


def clarify_saved_leaves(recipe):
    """Present old built-in snapshots with explicit leaves, without saving them."""
    if recipe.get('id'):
        return recipe
    choices = {'leafy greens': 'baby spinach', 'salad leaves': 'mixed salad leaves'}
    changed = False
    estimated = False

    def clarify(lines):
        nonlocal changed, estimated
        result = []
        for line in lines:
            key = shopping_key(line)
            if key in choices:
                converted, estimate = leaf_shopping_lines(key, [line])
                value = converted[0].replace(key, choices[key])
                if value != line:
                    changed = True
                    estimated |= estimate
                result.append(value)
            else:
                result.append(line)
        return result

    ingredients = clarify(recipe.get('ingredients', []))
    lunch = recipe.get('lunch')
    extras = clarify(lunch.get('extra_ingredients', [])) if isinstance(lunch, dict) else []
    if not changed:
        return recipe
    from copy import deepcopy

    result = deepcopy(recipe)
    result['ingredients'] = ingredients
    if isinstance(lunch, dict) and 'extra_ingredients' in lunch:
        result['lunch']['extra_ingredients'] = extras
    result['method'] = [step.replace('leafy greens', 'baby spinach') for step in recipe.get('method', [])]
    note = ('Generic greens are shown as baby spinach; salad leaves as mixed salad leaves. '
            'These are suggested ingredient choices.')
    if estimated:
        note += f' Former handfuls use a planning estimate of {LEAF_HANDFUL_GRAMS}g per handful, multiplied by any existing portion factor.'
    result['ingredient_notes'] = ' '.join(filter(None, [recipe.get('ingredient_notes'), note]))
    return result


BEEF_CUTS = {
    "Beef Kofta & Tahini Flatbread": "lean beef mince",
    "Harissa Beef Couscous": "lean beef strips",
    "Beef Meatball Pasta": "lean beef mince",
    "Quick Beef Bolognese": "lean beef mince",
    "Beef Tacos": "lean beef mince",
    "Chilli Con Carne": "lean beef mince",
    "Beef Broccoli Noodles": "lean beef strips",
    "Korean-style Beef Rice Bowl": "lean beef mince",
    "Quick Beef Keema": "lean beef mince",
    "Beef Pepper Rice": "lean beef strips",
    "Beef Satay Noodles": "lean beef strips",
    "Slow Beef Ragù": "lean stewing beef",
    "Beef Lasagne": "lean beef mince",
    "Beef Stew": "lean stewing beef",
    "Slow Thai-style Beef Curry": "lean stewing beef",
    "Moussaka-style Aubergine Bake": "lean beef mince",
}


def recipe_ingredient(line, recipe):
    """Clarify audited catalogue entries, including old saved meal snapshots."""
    parsed = parse(line)
    cut = BEEF_CUTS.get(recipe)
    if cut and parsed and parsed[2] == 'lean beef':
        return re.sub(r'lean beef$', cut, line, flags=re.IGNORECASE)
    return line


def tomato_choice(lines, recipes):
    # Counted tomatoes must remain medium-sized; a cherry tomato is not an
    # interchangeable piece. Variety suggestions don't change recipe amounts.
    parsed = [parse(line) for line in lines]
    if not parsed or any(not row or row[1] != 'g' for row in parsed):
        return 'medium round tomatoes'
    names = [name.casefold() for name in recipes]
    if names and all(any(word in name for word in ('salad', 'roast tomatoes')) for name in names):
        return 'cherry tomatoes'
    if names and all(any(word in name for word in ('sauce', 'ragù', 'ragu', 'bolognese')) for name in names):
        return 'plum tomatoes'
    return 'round tomatoes'


SALAD_LEAF_EXAMPLES = "e.g. lettuce, rocket or baby spinach"


def ingredient_display(line):
    """Examples clarify a mix without adding ingredients to recipe calculations."""
    if re.search(r"\bmixed salad leaves\b", line, re.IGNORECASE) and "e.g." not in line.casefold():
        return f"{line} ({SALAD_LEAF_EXAMPLES})"
    return line


def shopping_produce_note(key, lines):
    if key in LEAF_CHOICES:
        _, estimated = leaf_shopping_lines(key, lines)
        notes = []
        if key in {'salad leaves', 'mixed salad leaves'}:
            notes.append(f'Mixed salad leaves: {SALAD_LEAF_EXAMPLES}. Choose one suitable mix; these are examples, not separate items to buy.')
        if key == 'leafy greens':
            notes.append('Baby spinach is a suggested default where the recipe leaves the greens unspecified.')
        if estimated:
            notes.append('Shopping estimate: 25 g per handful, multiplied by the household portion factor. Actual handfuls vary; original recipe amounts are below.')
        return ' '.join(notes)
    if key == 'tomato':
        return ('The recipe does not name a variety, so this is a shopping suggestion. '
                'Counts mean medium round tomatoes; cherry or piccolo tomatoes are not a one-for-one replacement. '
                'Keep any weight specified by the recipe.')
    return ''


def shopping_amount(key, lines, *, pack_sizes=None, recipes=()):
    lines = list(lines)
    tomato = tomato_choice(lines, recipes) if key == 'tomato' else None
    lines, leaf_estimate = leaf_shopping_lines(key, lines)
    measured = []
    uncertain = False
    for line in lines:
        parsed = parse(line)
        if parsed and parsed[0] > 0 and parsed[1] != 'handful':
            measured.append(line)
        else:
            uncertain = True

    amounts = []
    for line in aggregate(measured, for_shopping=True, pack_sizes=pack_sizes):
        match = re.match(r'^(\d+)(g|ml) (.*)$', line)
        if match:
            count, unit, label = match.groups()
            if int(count) >= 1000:
                count = str(int(count) / 1000).removesuffix('.0')
                unit = {'g': 'kg', 'ml': 'L'}[unit]
            line = f'{count} {unit} {label}'
        amounts.append(line)
    if key == 'fresh herbs' and uncertain and not measured:
        return 'Flat-leaf parsley (suggested; to taste)'
    result = ' + '.join(amounts) or key
    if key in LEAF_CHOICES:
        result = result.replace(key, LEAF_CHOICES[key])
    if leaf_estimate:
        result = 'Approx. ' + result
    if tomato and measured:
        result = re.sub(r'\btomato(?:es)?\b', tomato, result) + ' (suggested)'
    if uncertain:
        result += ' (check extra amount)' if measured else ' (check amount)'
    return result


def number(amount):
    whole, remainder = divmod(amount.numerator, amount.denominator)
    if not remainder:
        return str(whole)
    fraction = f'{remainder}/{amount.denominator}'
    return f'{whole} {fraction}' if whole else fraction


def load_pack_sizes():
    from config import DATA_DIR

    try:
        value = json.loads((DATA_DIR / "pack_sizes.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def aggregate(items, *, for_shopping=False, pack_sizes=None):
    if for_shopping and pack_sizes is None:
        pack_sizes = load_pack_sizes()
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
            if amount > 1 and words[-1] in SINGULAR_TO_PLURAL:
                words[-1] = SINGULAR_TO_PLURAL[words[-1]]
            output.append(f'{number(amount)} {" ".join(words)}{note}')
        elif unit in {'g', 'ml'}:
            output.append(f'{number(amount)}{unit} {label}{note}')
        elif unit == 'tsp':
            chosen, quantity = ('tbsp', amount / 3) if amount >= 3 and amount % 3 == 0 else ('tsp', amount)
            output.append(f'{number(quantity)} {chosen} {label}')
        else:
            output.append(f'{number(amount)} {unit + ("s" if amount > 1 else "")} {label}{note}')
    return output
