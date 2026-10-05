"""Bounded, allowlisted JSON backups. Credentials and transaction caches are excluded."""
import json
import os
import math
import secrets
from datetime import datetime, timezone
from pathlib import Path
MAX_BYTES = 900_000
OBJECT_FILES = {'assets.json','rental_tax.json','finance_explanations.json','lifestyle.json','transaction_sources.json','finance_planning.json','bank_account_selection.json','calendar_location_overrides.json','receipt_recovery.json','savings_goals.json', 'bin_collections.json', 'daily_lists.json', 'premium_bonds.json', 'receipt_settings.json', 'subscriptions.json', 'savings.json',
                'investments.json', 'finance_settings.json', 'finance_categories.json',
                'food_shop_override.json', 'tesco_progress.json', 'meals_eaten.json'}
LIST_FILES = {'finance_monthly_snapshots.json','routines.json', 'future_tasks.json', 'wealth_history.json'}
FILES = OBJECT_FILES | LIST_FILES | {'to_buy.json', 'freezer.json', 'pantry.json'}

def _finite_tree(value, depth=0):
    if depth > 80:
        raise ValueError()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError()
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item, depth + 1)


def _amount(value):
    from decimal import Decimal
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError()


def _validate_file(name, content):
    from datetime import date
    if name == 'assets.json':
        from finance.assets import validate as validate_assets
        validate_assets(content)
    if name == 'rental_tax.json':
        from finance.rental_tax import validate as validate_tax
        validate_tax(content)
    if name == 'transaction_sources.json':
        from finance.transaction_sources import validate as validate_sources
        validate_sources(content)
    if name == 'finance_planning.json':
        from finance.planning import validate as validate_planning
        validate_planning(content)
    if name == 'receipt_settings.json':
        for key in ('features', 'one_shot', 'display', 'therapy_payment', 'finance', 'location', 'print_schedule', 'layout', 'api_health', 'private_backup'):
            if key in content and not isinstance(content[key], dict):
                raise ValueError()
        for key in ('features', 'one_shot'):
            if any(not isinstance(value, bool) for value in content.get(key, {}).values()):
                raise ValueError()
        if 'print_schedule' in content:
            import re
            config = content['print_schedule']
            if 'enabled' in config and not isinstance(config['enabled'], bool):
                raise ValueError()
            if 'time' in config and (not isinstance(config['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', config['time'])):
                raise ValueError()
        if 'private_backup' in content:
            config = content['private_backup']
            if type(config.get('enabled')) is not bool or type(config.get('keep')) is not int or config['keep'] not in (7, 14, 30):
                raise ValueError()
        if 'api_health' in content:
            from services.api_health import INTERVALS
            config=content['api_health']
            if type(config.get('enabled')) is not bool or type(config.get('interval_minutes')) is not int or config['interval_minutes'] not in INTERVALS: raise ValueError()
        if 'layout' in content:
            from receipt.layout import validate as validate_layout
            validate_layout(content['layout'])
        if 'location' in content:
            from receipt.location_settings import validate_location
            validate_location(content['location'])
    elif name == 'receipt_recovery.json':
        from receipt.recovery import validate as validate_recovery
        validate_recovery(content)
    elif name == 'calendar_location_overrides.json':
        from services.calendar_locations import validate as validate_locations
        validate_locations(content)
    elif name == 'bank_account_selection.json':
        from finance.bank_accounts import validate as validate_accounts
        validate_accounts(content)
    elif name == 'finance_settings.json':
        for field in ('hsbc_emergency_reserve','physical_cash_target','physical_cash_held','salary_savings_target'):
            if content.get(field) is not None: _amount(content[field])
        if content.get('physical_cash_date'): date.fromisoformat(content['physical_cash_date'])
    elif name == 'finance_monthly_snapshots.json':
        from web_control.finance_insights import validate as validate_snapshots
        validate_snapshots(content)
    elif name == 'lifestyle.json':
        from receipt.lifestyle import validate as validate_lifestyle
        validate_lifestyle(content)
    elif name == 'finance_explanations.json':
        from web_control.payment_explanations import store
        store().validate(content)
    elif name == 'savings_goals.json':
        from finance.savings_goals import validate as validate_goals
        validate_goals(content)
    elif name == 'bin_collections.json':
        from services.bin_collections import validate as validate_bins
        validate_bins(content)
    elif name == 'daily_lists.json':
        from actions.checklists import validate_state
        validate_state(content)
    elif name == 'subscriptions.json':
        for key in ('monthly', 'yearly', 'instalments'):
            for row in content.get(key, []):
                if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                    raise ValueError()
                for field in ('amount', 'monthly_payment', 'remaining_balance', 'paid_to_date', 'total_price'):
                    if row.get(field) is not None:
                        _amount(row[field])
                if row.get('match') is not None and (not isinstance(row['match'], list) or any(not isinstance(term, str) for term in row['match'])):
                    raise ValueError()
                for field in ('due_day', 'day'):
                    if row.get(field) is not None and (isinstance(row[field], bool) or not isinstance(row[field], int) or not 1 <= row[field] <= 31):
                        raise ValueError()
                for field in ('next_payment', 'renewal_date', 'end_date'):
                    if row.get(field):
                        date.fromisoformat(row[field])
    elif name in {'savings.json', 'investments.json'}:
        for row in content.get('accounts', []):
            if not isinstance(row, dict) or ('name' in row and not isinstance(row['name'], str)):
                raise ValueError()
            _amount(row.get('balance' if name == 'savings.json' else 'value', 0))
    elif name == 'wealth_history.json':
        for row in content:
            if not all(isinstance(row.get(key), str) for key in ('id', 'name', 'date')) or row.get('kind') not in {'savings', 'investment'}:
                raise ValueError()
            date.fromisoformat(row['date'])
            _amount(row['balance'])
            for key in ('deposits', 'withdrawals'):
                if row.get(key) is not None:
                    _amount(row[key])
    elif name == 'food_shop_override.json':
        if not isinstance(content.get('items'), list) or any(not isinstance(item, str) for item in content['items']):
            raise ValueError()


def validate(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Backup exceeds the 900 KB limit.')
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _finite_tree(value)
        files = value['files']
        if value.get('version') != 1 or not isinstance(files, dict) or not files:
            raise ValueError()
        for name, content in files.items():
            if name not in FILES:
                raise ValueError()
            if name in OBJECT_FILES and not isinstance(content, dict):
                raise ValueError()
            if name in LIST_FILES and (not isinstance(content, list) or any(not isinstance(row, dict) for row in content)):
                raise ValueError()
            if not isinstance(content, (dict, list)):
                raise ValueError()
            if name in {'savings.json', 'investments.json'} and not isinstance(content.get('accounts', []), list):
                raise ValueError()
            if name == 'to_buy.json' and (not isinstance(content, dict) or not isinstance(content.get('items'), list) or any(not isinstance(item, str) for item in content['items'])):
                raise ValueError()
            if name == 'future_tasks.json' and any(not all(isinstance(row.get(key), str) for key in ('id', 'title', 'next_step')) or not isinstance(row.get('done'), bool) for row in content):
                raise ValueError()
            if name == 'premium_bonds.json':
                from finance.premium_bonds import validate_data
                validate_data(content)
            if name == 'subscriptions.json' and any(not isinstance(content.get(key, []), list) for key in ('monthly', 'yearly', 'instalments')):
                raise ValueError()
            _validate_file(name, content)
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
        raise ValueError('Use a valid Receipt Control backup with supported local data files.') from None
    return value

def export(root):
    files = {}
    for name in sorted(FILES):
        path = root / 'data' / name
        if path.exists():
            files[name] = json.loads(path.read_text(encoding='utf-8'))
    if not files:
        raise ValueError('No supported local data exists to back up yet.')
    value = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': files}
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('Local data exceeds the 900 KB backup limit. Copy your private data folder manually.')
    validate(raw)
    return raw

def private_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def restore(root, value):
    validate(json.dumps(value).encode())
    originals = {name: (root / 'data' / name).read_bytes() if (root / 'data' / name).exists() else None
                 for name in value['files']}
    # Keep the exact previous bytes for rollback, including files that did not exist.
    rollback = {'version': 1, 'originals': {name: raw.decode('utf-8') if raw is not None else None
                                        for name, raw in originals.items()}}
    target = root / 'data' / 'private_backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(6) + '.json')
    private_write(target, json.dumps(rollback).encode())
    try:
        for name, content in value['files'].items():
            private_write(root / 'data' / name, json.dumps(content, ensure_ascii=False, allow_nan=False).encode())
    except Exception as cause:
        rollback_failed = False
        for name, raw in originals.items():
            try:
                if raw is None:
                    (root / 'data' / name).unlink(missing_ok=True)
                else:
                    private_write(root / 'data' / name, raw)
            except OSError:
                rollback_failed = True
        if rollback_failed:
            raise RestoreRecoveryError('Restore rollback incomplete; recover original files from data/private_backups.') from cause
        raise


class RestoreRecoveryError(OSError):
    """The rollback record must be used for manual recovery."""
