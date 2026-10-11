"""Private Away mode and retention preferences, shared by recipes and jobs."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from storage import PrivateStore
from receipt.local_time import uk_today
FILE = Path(__file__).resolve().parents[1] / 'data' / 'lifestyle.json'
DEFAULT = {'away': {'enabled': False, 'departure': '', 'return': '', 'pause_meals': True, 'travel_meals': []}, 'retention': {'receipts': 0, 'details': 0}, 'credit_cards': []}


def validate(value):
    if not isinstance(value, dict): raise ValueError('Invalid preferences')
    away = value.get('away', {})
    if not isinstance(away, dict) or type(away.get('enabled')) is not bool or type(away.get('pause_meals')) is not bool:
        raise ValueError('Invalid Away mode')
    for field in ('departure', 'return'):
        if away.get(field): date.fromisoformat(away[field])
    if away.get('enabled') and not away.get('departure'): raise ValueError('Choose a departure date')
    if away.get('return') and (not away.get('departure') or away['return'] <= away['departure']): raise ValueError('Return must be after departure; home meals resume on your return date')
    if not isinstance(away.get('travel_meals'), list) or len(away['travel_meals']) > 366: raise ValueError('Invalid travel meal dates')
    for day in away['travel_meals']: date.fromisoformat(day)
    retention = value.get('retention', {})
    if not isinstance(retention, dict) or any(type(retention.get(key)) is not int or retention[key] not in (0,30,90,180,365) for key in ('receipts','details')):
        raise ValueError('Choose a supported retention period')

    from finance.money import parse
    cards = value.get('credit_cards', [])
    if not isinstance(cards, list) or len(cards) > 20: raise ValueError('Use up to 20 credit cards')
    names = set()
    for card in cards:
        if not isinstance(card,dict) or not isinstance(card.get('name'),str) or not card['name'].strip() or len(card['name']) > 90 or card['name'].casefold() in names: raise ValueError('Use a unique credit-card name')
        names.add(card['name'].casefold())
        limit = parse(card.get('limit'))
        if limit is None or not 0 < limit <= 10000000 or card.get('provider') not in ('AMEX','OTHER'): raise ValueError('Enter a valid credit limit and balance source')
        if card.get('used') is not None and (parse(card['used']) is None or parse(card['used']) < 0): raise ValueError('Enter a non-negative used balance')
        if card.get('as_of'): date.fromisoformat(card['as_of'])


def store(): return PrivateStore(FILE, default=lambda: deepcopy(DEFAULT), validate=validate)
def load(): return store().read()


def active(on=None, settings=None):
    on = on or uk_today()
    away = (settings if settings is not None else load())['away']
    return bool(away['enabled'] and away['departure'] <= on.isoformat() and (not away['return'] or on.isoformat() < away['return']))


def skip_meal(on, settings=None):
    settings = settings if settings is not None else load()
    return active(on, settings) and settings['away']['pause_meals'] and on.isoformat() not in settings['away']['travel_meals']


def apply_plan(plan, planner, settings=None):
    settings = settings if settings is not None else load()
    result = deepcopy(plan)
    excluded = []
    for index, meal in enumerate(result.get('meals', [])):
        on = date.fromisoformat(meal['date'])
        if skip_meal(on, settings):
            excluded.append({'date': meal['date'], 'name': meal.get('recipe', {}).get('name') or meal.get('name', 'Planned meal')})
            result['meals'][index] = {'date': meal['date'], 'kind': 'away', 'name': 'Away - home meal paused', 'overview': 'Recipe ingredients excluded from shopping.'}
    original = planner.build_shopping_list(plan, include_away=True)
    result['away_excluded'] = excluded
    result['shopping'] = planner.build_shopping_list(result)
    needed = {item for group in result['shopping'].values() for item in group}
    result['away_excluded_ingredients'] = [item for group in original.values() for item in group if item not in needed]
    result['prep'] = planner.build_sunday_prep(result)
    result['estimated_cost'] = planner.estimate_week_cost(result)
    return result


def prune(root, on=None):
    """Prune only opted-in receipts and dated review detail; retain ledgers/settings."""
    import json
    from storage import write_json
    on = on or uk_today()
    config = load()['retention']; removed = {'receipts': 0, 'details': 0}
    if config['receipts']:
        cutoff = (on - timedelta(days=config['receipts'])).isoformat()
        for path in (root / 'data' / 'receipt_archive').glob('*.json'):
            if path.is_symlink(): continue
            try:
                value = json.loads(path.read_text())
                from receipt.local_time import uk_receipt_time
                if not uk_receipt_time(value.get('captured_at')): continue
                from datetime import datetime
                from zoneinfo import ZoneInfo
                stamp = datetime.fromisoformat(value['captured_at']).astimezone(ZoneInfo('Europe/London')).date().isoformat()
                if stamp < cutoff: path.unlink(); removed['receipts'] += 1
            except (ValueError, OSError, KeyError, TypeError): continue
    if config['details']:
        cutoff = (on - timedelta(days=config['details'])).isoformat()
        path = root / 'data' / 'finance_review_queue.json'
        if path.exists() and not path.is_symlink():
            try:
                value = json.loads(path.read_text())
                for field in ('payments','reviewable','audit'):
                    if field in value:
                        kept = [row for row in value[field] if str(row.get('date', row.get('at', '9999')))[:10] >= cutoff]
                        removed['details'] += len(value[field]) - len(kept); value[field] = kept
                write_json(path, value)
            except (ValueError, OSError, TypeError): pass
    return removed


def prune_explanations(root, on=None):
    import json
    from storage import write_json
    days = load()['retention']['details']
    if not days: return
    cutoff = ((on or uk_today()) - timedelta(days=days)).isoformat()
    path = root / 'data' / 'finance_explanations.json'
    if not path.exists() or path.is_symlink(): return
    value = json.loads(path.read_text())
    for field in ('payments', 'audit'):
        value[field] = [row for row in value.get(field, []) if str(row.get('at', row.get('date', '9999')))[:10] >= cutoff]
    write_json(path, value)
