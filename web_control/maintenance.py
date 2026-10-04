"""Daily private backups while Receipt Control runs; no external uploads."""
import fcntl
import os
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo
from web_control import private_backup as backup
from receipt_settings import load_receipt_settings

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'auto-\d{8}T\d{6}-[a-f0-9]{12}\.json')
_START = Lock()
_THREAD = None


def options(settings=None):
    value = (settings if settings is not None else load_receipt_settings()).get('private_backup', {})
    if not isinstance(value, dict): value = {}
    retention = value.get('keep', 14)
    if type(retention) is not int or retention not in (7, 14, 30): retention = 14
    return {'enabled': value.get('enabled', True) is True, 'keep': retention}


def saved(root=ROOT):
    rows = []
    directory = root / 'data' / 'private_backups'
    for path in sorted(directory.glob('auto-*.json'), reverse=True):
        if not PATTERN.fullmatch(path.name) or path.is_symlink(): continue
        try:
            with path.open('rb') as stream:
                value = backup.validate(stream.read(backup.MAX_BYTES + 1))
            local = datetime.fromisoformat(value['created_at']).astimezone(ZoneInfo('Europe/London'))
            rows.append({'name': path.name, 'local': local, 'files': len(value['files'])})
        except (OSError, ValueError, KeyError, TypeError): continue
    return sorted(rows, key=lambda row: row['local'].timestamp(), reverse=True)


def read_saved(root, name):
    if not PATTERN.fullmatch(name): raise ValueError('Backup unavailable.')
    path = root / 'data' / 'private_backups' / name
    if path.is_symlink(): raise ValueError('Backup unavailable.')
    with path.open('rb') as stream:
        raw = stream.read(backup.MAX_BYTES + 1)
    backup.validate(raw)
    return raw


def create(root=ROOT, *, force=False, now=None, settings=None):
    config = options(settings)
    if not force and not config['enabled']: return False
    now = now or datetime.now(ZoneInfo('Europe/London'))
    directory = root / 'data' / 'private_backups'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'maintenance.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return False
        for name in ('.print_now.lock', '.live_preview.lock'):
            try:
                pid = int((root / 'data' / name).read_text())
                if 0 < pid <= 2_147_483_647:
                    os.kill(pid, 0)
                    return False
            except PermissionError: return False
            except (OSError, ValueError): pass
        rows = saved(root)
        if not force and rows and rows[0]['local'].date() == now.astimezone(ZoneInfo('Europe/London')).date(): return False
        value = backup.validate(backup.export(root))
        value['created_at'] = now.astimezone(timezone.utc).isoformat()
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        backup.validate(raw)
        import secrets
        name = now.strftime('auto-%Y%m%dT%H%M%S-') + secrets.token_hex(6) + '.json'
        backup.private_write(directory / name, raw)
        # Prune only valid automatic snapshots. Restore rollback records stay intact.
        for row in saved(root)[config['keep']:]:
            (directory / row['name']).unlink(missing_ok=True)
        return True


def loop(stop):
    while not stop.is_set():
        try:
            create()
            from web_control.backup_health import check
            check(ROOT)
        except (OSError, ValueError): logging.getLogger(__name__).warning('Private backup unavailable; check local data and disk space.')
        stop.wait(60)


def start_monitor():
    global _THREAD
    with _START:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = Thread(target=loop, args=(Event(),), name='receipt-private-backup', daemon=True)
            _THREAD.start()
        return _THREAD
