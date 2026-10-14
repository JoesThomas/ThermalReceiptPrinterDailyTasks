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


def _create(root=ROOT, *, force=False, now=None, settings=None):
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
        try:
            for row in saved(root)[config['keep']:]:
                (directory / row['name']).unlink(missing_ok=True)
        except OSError as error:
            logging.getLogger(__name__).warning('Private snapshot saved; retention cleanup unavailable: %s', backup.failure_message(error))
        return True


def attempt_state(root=ROOT):
    from storage import PrivateStore
    try:
        value = PrivateStore(root/'data'/'backup_attempt.json', default=dict, max_bytes=10000).read()
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def create(root=ROOT, *, force=False, now=None, settings=None):
    now = now or datetime.now(ZoneInfo('Europe/London'))
    previous = attempt_state(root)
    from services.retry_policy import pending
    if not force and pending(previous.get('next_retry'), now.timestamp()):
        return False
    try:
        created = _create(root, force=force, now=now, settings=settings)
    except (OSError, ValueError) as error:
        from storage import write_json
        no_data = isinstance(error, backup.BackupExportError) and error.kind == 'no_data'
        state = dict(state='idle' if no_data else 'failed', attempted_at=now.astimezone(timezone.utc).isoformat(),
                     message=backup.failure_message(error),
                     next_retry=None if no_data else datetime.fromtimestamp(now.timestamp()+900, timezone.utc).isoformat())
        try:
            write_json(root/'data'/'backup_attempt.json', state)
        except OSError:
            pass  # The safe log diagnosis must still work when the disk cannot be written.
        if no_data and not force:
            return False
        raise
    if created:
        from storage import write_json
        try:
            write_json(root/'data'/'backup_attempt.json', dict(state='saved', attempted_at=now.astimezone(timezone.utc).isoformat(),
                                                             message='Private snapshot saved.', next_retry=None))
        except OSError:
            pass
    return created


def run_once(root=ROOT, *, warnings=None, now=None):
    """One failing maintenance task must not block other independent tasks."""
    from web_control.backup_health import check
    from receipt.lifestyle import prune, prune_explanations
    from receipt.archive_policy import prune as prune_archive
    now = now or datetime.now(ZoneInfo('Europe/London'))
    warnings = warnings if warnings is not None else {}
    from services.vehicle_records import sync_mot_tasks
    jobs = [('MOT task reminders', lambda: sync_mot_tasks(today=now.astimezone(ZoneInfo('Europe/London')).date(), root=root)),
            ('Private backup', lambda: create(root, now=now)),
            ('Backup recovery check', lambda: check(root, now=now)),
            ('Lifestyle cleanup', lambda: prune(root)),
            ('Finance explanation cleanup', lambda: prune_explanations(root)),
            ('Receipt archive cleanup', lambda: prune_archive(root))]
    for stage, action in jobs:
        previous = warnings.get(stage)
        if previous and len(previous) > 2 and previous[2] > now.timestamp():
            if stage != 'Private backup' or attempt_state(root).get('state') != 'saved':
                continue
        try:
            action()
        except (OSError, ValueError) as error:
            message = backup.failure_message(error)
            previous = warnings.get(stage)
            if not previous or previous[0] != message or now.timestamp()-previous[1] >= 3600:
                logging.getLogger(__name__).warning('%s unavailable: %s', stage, message)
                last_warning = now.timestamp()
            else:
                last_warning = previous[1]
            warnings[stage] = (message, last_warning, now.timestamp()+900)
        else:
            if stage == 'Private backup':
                state = attempt_state(root).get('state')
                if state == 'idle':
                    warnings.pop(stage, None)
                    continue
                if state != 'saved':
                    continue  # A delayed/busy retry is not a successful recovery.
            if stage in warnings:
                logging.getLogger(__name__).info('%s available again.', stage)
                warnings.pop(stage)
    return warnings


def loop(stop):
    warnings = {}
    while not stop.is_set():
        run_once(warnings=warnings)
        stop.wait(60)


def start_monitor():
    global _THREAD
    with _START:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = Thread(target=loop, args=(Event(),), name='receipt-private-backup', daemon=True)
            _THREAD.start()
        return _THREAD
