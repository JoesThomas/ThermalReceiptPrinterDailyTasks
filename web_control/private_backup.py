"""Bounded, allowlisted JSON backups. Credentials and transaction caches are excluded."""
import json
import os
import math
import secrets
from datetime import datetime, timezone
from pathlib import Path
MAX_BYTES = 900_000
OBJECT_FILES = {'bank_overdrafts.json','vehicles.json','birthdays.csv','finance_scenarios.json', 'receipt_settings.last-good.json','receipt_archive_settings.json','finance_reviews.json','assets.json','rental_tax.json','finance_explanations.json','lifestyle.json','transaction_sources.json','finance_planning.json','bank_account_selection.json','calendar_location_overrides.json','receipt_recovery.json','savings_goals.json', 'bin_collections.json', 'daily_lists.json', 'premium_bonds.json', 'receipt_settings.json', 'subscriptions.json', 'savings.json',
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
    if name == 'birthdays.csv':
        from actions.birthdays import validate_rows
        if set(content) != {'rows'}: raise ValueError('Invalid birthday backup.')
        rows = content['rows']
        if not isinstance(rows, list): raise ValueError('Invalid birthday backup.')
        # Older backups included profile links; discard them when restoring.
        rows = [{key: value for key, value in row.items() if key != 'profile'} if isinstance(row, dict) else row for row in rows]
        validate_rows(rows)
        content['rows'] = rows
    if name == 'vehicles.json':
        from services.vehicle_records import validate as validate_vehicles
        validate_vehicles(content)
    if name == 'finance_reviews.json':
        from finance.reviews import validate as validate_reviews
        validate_reviews(content)
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
    if name in {'receipt_settings.json', 'receipt_settings.last-good.json'}:
        from receipt_settings import validate_settings
        validate_settings(content)
    elif name == 'finance_scenarios.json':
        from finance.scenario_presets import validate_state
        validate_state(content)
    elif name == 'receipt_archive_settings.json':
        from receipt.archive_policy import validate as validate_archive
        validate_archive(content)
    elif name == 'receipt_recovery.json':
        from receipt.recovery import validate as validate_recovery
        validate_recovery(content)
    elif name == 'calendar_location_overrides.json':
        from services.calendar_locations import validate as validate_locations
        validate_locations(content)
    elif name == 'bank_overdrafts.json':
        from finance.bank_overdrafts import validate as validate_overdrafts
        validate_overdrafts(content)
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

class BackupExportError(ValueError):
    """Safe diagnosis; never includes private values or an underlying exception."""
    def __init__(self, kind, filename=None, detail=None):
        self.kind = kind
        self.filename = filename if filename in FILES else None
        messages = {
            'invalid_json': 'is not valid UTF-8 JSON',
            'invalid_data': 'does not match the supported backup format',
            'too_large': 'exceeds the 900 KB backup limit',
            'linked_file': 'is a linked file; use a regular local data file',
            'no_data': 'No supported local data exists to back up yet',
        }
        message = messages[kind]
        result = f'data/{self.filename} {message}.' if self.filename else message[0].upper()+message[1:]+'.'
        if detail and self.filename in {'receipt_settings.json', 'receipt_settings.last-good.json'}:
            result += ' '+detail
        super().__init__(result)


def file_content(name, raw):
    if name == 'birthdays.csv':
        from actions.birthdays import parse_csv
        rows, _ = parse_csv(raw)
        return {'rows': rows}
    return json.loads(raw.decode('utf-8'))


def export(root):
    files = {}
    for name in sorted(FILES):
        path = root / 'data' / name
        if path.is_symlink():
            raise BackupExportError('linked_file', name)
        try:
            with path.open('rb') as stream:
                raw_file = stream.read(MAX_BYTES+1)
        except FileNotFoundError:
            continue
        if len(raw_file) > MAX_BYTES:
            raise BackupExportError('too_large', name)
        try:
            content = file_content(name, raw_file)
        except (ValueError, RecursionError):
            raise BackupExportError('invalid_json', name) from None
        try:
            validate(json.dumps({'version':1, 'files':{name:content}}, ensure_ascii=False, allow_nan=False).encode())
        except (ValueError, TypeError, ArithmeticError, RecursionError):
            detail = None
            if name in {'receipt_settings.json', 'receipt_settings.last-good.json'}:
                from receipt_settings import settings_diagnosis
                detail = settings_diagnosis(content)
            raise BackupExportError('invalid_data', name, detail) from None
        files[name] = content
    if not files:
        raise BackupExportError('no_data')
    value = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': files}
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise BackupExportError('too_large')
    validate(raw)
    return raw


def failure_message(error):
    if isinstance(error, BackupExportError):
        return str(error)
    import errno
    if isinstance(error, OSError):
        filename = Path(str(error.filename)).name if error.filename else None
        prefix = f'data/{filename}: ' if filename in FILES else ''
        return prefix + {
            errno.ENOSPC: 'Not enough free disk space to save the backup.',
            errno.EACCES: 'Permission denied while reading local data or writing the backup.',
            errno.EPERM: 'Permission denied while reading local data or writing the backup.',
            errno.EROFS: 'The backup location is on a read-only filesystem.',
            errno.EISDIR: 'A supported data file is a directory; check the local data folder.',
            errno.EDQUOT: 'The filesystem quota is full; the backup could not be saved.',
        }.get(error.errno, 'A filesystem operation failed while maintaining the backup; check local data access and storage.')
    return 'Local data could not be validated; run the private backup check to identify the file.'


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
            if name == 'birthdays.csv':
                from actions.birthdays import csv_bytes
                raw = csv_bytes(content['rows'])
            else:
                raw = json.dumps(content, ensure_ascii=False, allow_nan=False).encode()
            private_write(root / 'data' / name, raw)
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
