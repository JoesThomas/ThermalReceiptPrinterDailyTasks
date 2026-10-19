"""Shared, offline food-storage guidance for web and receipt output.

Durations start at actual preparation, not the print time. Dates are conditional
planning prompts; they do not certify a stored batch or replace earlier labels.
Source rationale and conservative application choices: docs/food-storage.md.
"""
from datetime import date, timedelta
import re

SOURCES = (
    ('Chilling, freezing and defrosting', 'https://www.gov.uk/government/publications/how-to-chill-freeze-and-defrost-food-safely/how-to-chill-freeze-and-defrost-food-safely'),
    ('Rice and eggs', 'https://www.gov.uk/government/publications/home-food-fact-checker/home-food-fact-checker'),
    ('Cooking and reheating', 'https://www.gov.uk/government/publications/cooking-your-food/cooking-your-food'),
)
FRIDGE = 'Fridge 0-5C; clean covered container, above and separate from raw meat/fish.'
COOL = 'Divide into small portions; cool and refrigerate within 1-2 hours.'
FREEZE = 'Freeze suitable surplus promptly in labelled portions at -18C.'
THAW = 'Thaw in the fridge; use within 24 hours of fully defrosting.'
LABEL = 'Earlier ingredient use-by/opened-pack instructions still apply. Mixing does not restart their life.'
REHEAT = 'Reheat only once, until steaming hot throughout.'

# These are deliberately short planning windows, not validated product shelf lives.
_COMPONENTS = {
    'mayonnaise': (0, 'Keep refrigerated; use on the day made (conservative app rule). Use pasteurised egg; do not freeze; make fresh for later meals.'),
    'sriracha_mayo': (0, 'Keep refrigerated; use on the day mixed (conservative app rule). Do not freeze; mix fresh for later meals.'),
    'tahini_yoghurt': (48, 'Keep refrigerated; freezing is not suggested for this dressing.'),
    'quick_pickled_onions': (48, 'Keep refrigerated, not in the cupboard. This quick pickle is not shelf-stable; no validated preserving life.'),
    'shawarma_spice': (None, 'Dry airtight jar in a cool, dry cupboard. Use the earliest spice best-before for quality; keep moisture out.'),
    'chicken_stock': (48, 'Freeze surplus stock in measured portions. Only use a safely stored carcass; stock-making does not rescue old leftovers.'),
    'pesto': (48, 'Keep refrigerated, never in the cupboard. Freeze surplus promptly in small portions.'),
    'focaccia': (None, 'Plain bread: airtight in a cool, dry cupboard; best within 2 days (quality guide). Slice and freeze surplus once cool; best within 3-4 months frozen (quality). Refrigerate perishable toppings; use within 48 hours.'),
    'fresh_pasta': (24, 'Raw egg dough: wrap and refrigerate separately from ready-to-eat food. Cook within 24 hours or freeze shaped portions promptly (conservative app rule).'),
}


def _deadline(hours, made_on, action='use'):
    if hours is None:
        return ''
    if hours == 0:
        return f'If made today: use today, {made_on:%a %d %b}; discard remaining sauce.'
    end = made_on + timedelta(hours=hours)
    return f'If made today: {action} by {end:%a %d %b}, within {hours} hours of preparation (not end of day).'


def component_guidance(item, made_on: date):
    """Works with old cached plans and new/custom component definitions."""
    if item.get('action') != 'make':
        return ['Bought item: follow pack storage, use-by and after-opening instructions.']
    cid = item.get('id', '')
    hours, note = _COMPONENTS.get(cid, (None, 'No verified storage period for this item. Follow a tested recipe and ingredient labels; do not assume it keeps all week.'))
    rows = [note]
    if cid not in {'shawarma_spice', 'focaccia'}:
        rows.insert(0, FRIDGE if cid != 'fresh_pasta' else 'Fridge 0-5C; sealed container, separate from ready-to-eat food.')
    if hours:
        rows.append(f'Use within {hours} hours of preparation; sooner if an ingredient requires it.')
    deadline = _deadline(hours, made_on)
    if deadline:
        rows.append(deadline)
    if cid in {'chicken_stock', 'focaccia'}:
        rows.append(COOL)
    if cid in {'chicken_stock', 'pesto', 'fresh_pasta', 'focaccia'}:
        rows.extend([FREEZE, THAW])
    if cid == 'chicken_stock':
        rows.append(REHEAT)
    rows.append(LABEL)
    # Preserve additional custom notes from local component files.
    custom = item.get('details', {}).get('storage')
    if custom:
        rows.append(str(custom))
    return rows


def contains_rice(recipe):
    # Ingredients, not lunch descriptions: avoid missing rice reused in a wrap.
    ingredients = ' '.join(str(x) for x in recipe.get('ingredients', []))
    return bool(re.search(r'\b(?:rice|risotto)\b', ingredients, re.I))


def leftover_guidance(recipe, cooked_on: date):
    rice = contains_rice(recipe)
    hours = 24 if rice else 48
    rows = [FRIDGE]
    rows.append('Rice: cool quickly, ideally within 1 hour; refrigerate or freeze promptly. Do not leave it cooling in the pan/cooker.' if rice else COOL)
    rows.extend([f'Use within {hours} hours of cooking; freeze suitable surplus promptly, not at the deadline.', _deadline(hours, cooked_on, 'use or freeze'), FREEZE])
    rows.append('Rice: thaw in the fridge, then reheat until steaming hot and eat immediately.' if rice else THAW)
    rows.extend([REHEAT, 'Reserve lunch before serving; keep salad/dressing separate. Earlier ingredient limits still apply.'])
    return rows


def receipt_lines(rows, compact=False):
    """Keep essential handling, time and location even on a quick receipt."""
    if not compact:
        return rows
    short = {
        FRIDGE: 'Covered in fridge 0-5C, above raw food.',
        COOL: 'Cool in small portions; fridge in 1-2h.',
        FREEZE: 'Freeze suitable surplus promptly (-18C); label portions.',
        THAW: 'Thaw in fridge; use within 24h thawed.',
        LABEL: 'Earlier ingredient/pack limits apply.',
        REHEAT: 'Reheat once; steaming hot throughout.',
        'Rice: cool quickly, ideally within 1 hour; refrigerate or freeze promptly. Do not leave it cooling in the pan/cooker.': 'Rice: cool quickly, ideally within 1h; fridge/freezer, not left in cooker.',
        'Rice: thaw in the fridge, then reheat until steaming hot and eat immediately.': 'Rice: thaw in fridge; reheat and eat immediately.',
        'Reserve lunch before serving; keep salad/dressing separate. Earlier ingredient limits still apply.': 'Pack lunch separately; earlier ingredient limits apply.',
    }
    return [short.get(s, s) for s in rows
            if not s.startswith('Use within ') or not any(x.startswith('If made today:') for x in rows)]


def web_guidance(planned, components, today):
    recipe = planned.get('recipe', {}) if planned and planned.get('kind') == 'recipe' else None
    return {
        'leftovers': leftover_guidance(recipe, today) if recipe is not None else [],
        'components': [{'name': c.get('name', c.get('id', 'Prep item')),
                        'lines': component_guidance({'id': c.get('id'), 'action': 'make', 'details': c.get('make', {})}, today)}
                       for c in components if c.get('make')],
        'sources': SOURCES,
    }
