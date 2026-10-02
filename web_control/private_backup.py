"""Bounded, allowlisted JSON backups. Credentials and transaction caches are excluded."""
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
MAX_BYTES = 900_000
OBJECT_FILES = {'premium_bonds.json', 'receipt_settings.json', 'subscriptions.json', 'savings.json',
                'investments.json', 'finance_settings.json', 'finance_categories.json',
                'food_shop_override.json', 'tesco_progress.json', 'meals_eaten.json'}
LIST_FILES = {'routines.json', 'future_tasks.json', 'wealth_history.json'}
FILES = OBJECT_FILES | LIST_FILES | {'to_buy.json', 'freezer.json', 'pantry.json'}

def validate(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Backup exceeds the 900 KB limit.')
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
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
    except (ValueError, TypeError, KeyError, RecursionError):
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
    except Exception:
        for name, raw in originals.items():
            if raw is None:
                (root / 'data' / name).unlink(missing_ok=True)
            else:
                private_write(root / 'data' / name, raw)
        raise
