"""Private bounded cache of parsed calendar/delivery results and timing metadata."""
import fcntl
import os
import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from storage import write_json

FILE = Path(__file__).resolve().parents[1] / 'data' / 'source_cache.json'


def encode(value):
    if isinstance(value, datetime): return {'_datetime': value.isoformat()}
    if isinstance(value, date): return {'_date': value.isoformat()}
    if isinstance(value, list): return [encode(x) for x in value]
    if isinstance(value, dict): return {key: encode(x) for key, x in value.items()}
    return value


def decode(value):
    if isinstance(value, list): return [decode(x) for x in value]
    if isinstance(value, dict):
        if set(value) == {'_datetime'}: return datetime.fromisoformat(value['_datetime'])
        if set(value) == {'_date'}: return date.fromisoformat(value['_date'])
        return {key: decode(x) for key, x in value.items()}
    return value


def load():
    try:
        with FILE.open('rb') as stream: raw = stream.read(4_000_001)
        if len(raw) > 4_000_000: return {}
        value = json.loads(raw)
        return {key:row for key,row in value.items() if isinstance(row,dict)} if isinstance(value,dict) else {}
    except (OSError, ValueError): return {}


@contextmanager
def locked():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(lock, fcntl.LOCK_UN)


def key(name, identity):
    return hashlib.sha256((name + '\n' + identity).encode()).hexdigest()


def get(name, identity, collect, *, ttl=300, max_age=86400):
    identity = key(name, identity)
    start = time.monotonic()
    with locked(): row = load().get(identity, {})
    if not isinstance(row, dict): row = {}
    age = time.time() - row.get('saved_epoch', 0) if isinstance(row.get('saved_epoch', 0), (int, float)) else float('inf')
    has_cache = isinstance(row.get('result'), list) and 0 <= age <= max_age
    try: cached_result = decode(row['result']) if has_cache else None
    except (TypeError,ValueError): has_cache, cached_result = False, None
    retry = os.environ.get('RECEIPT_REFRESH_SOURCE', '')
    if retry and name != retry and not has_cache:
        from receipt.freshness import mark
        mark(name, 'unavailable')
        raise ValueError('No valid saved result for this source during a targeted retry')
    if has_cache and ((retry and name != retry) or (not retry and age < ttl and not row.get('refresh'))):
        result, status = cached_result, 'cached'
    else:
        try:
            result = collect()
            status = 'checked'
            if isinstance(result, tuple) and len(result) == 2:
                result, status = result
                if status not in {'checked', 'partial'}: raise ValueError('Invalid source status')
            if not isinstance(result, list): raise ValueError('Invalid source result')
            packed = encode(result)
            if len(json.dumps(packed).encode()) > 2_000_000: raise ValueError('Source result too large')
            if status == 'partial' and has_cache:
                result, status = cached_result, 'cached after partial result'
            else:
                row = {'result': packed, 'saved_epoch': time.time(), 'source_checked_at': datetime.now(timezone.utc).isoformat()}
        except Exception:
            if not has_cache:
                record(identity, {**row, 'name': name, 'status': 'unavailable', 'duration_ms': round((time.monotonic()-start)*1000),
                                  'attempted_at': datetime.now(timezone.utc).isoformat()})
                from receipt.freshness import mark
                mark(name, 'unavailable')
                raise
            result, status = cached_result, 'cached after error'
    row.update(name=name, status=status, duration_ms=round((time.monotonic()-start)*1000),
               attempted_at=datetime.now(timezone.utc).isoformat())
    record(identity, row)
    from receipt.freshness import mark
    mark(name, status, source_checked_at=row.get('source_checked_at'), duration_ms=row['duration_ms'])
    return result


def record(identity, row):
    with locked():
        state = load(); state[identity] = row
        state = dict(sorted(state.items(), key=lambda x: str(x[1].get('attempted_at', '')), reverse=True)[:32])
        write_json(FILE, state)


def refresh():
    with locked():
        state = load()
        for row in state.values():
            if isinstance(row, dict): row['refresh'] = True
        write_json(FILE, state)


def timings():
    rows = {}
    for row in load().values():
        if isinstance(row, dict) and isinstance(row.get('name'), str):
            old = rows.get(row['name'], {})
            if row.get('attempted_at', '') > old.get('attempted_at', ''):
                rows[row['name']] = {key: row.get(key) for key in ('name','status','duration_ms','attempted_at','source_checked_at')}
    return list(rows.values())
