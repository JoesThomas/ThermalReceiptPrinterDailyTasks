"""Private delivery checklist shared by receipt generation and the web app."""
import hashlib
from html import unescape
import json
from contextlib import contextmanager
from pathlib import Path
import fcntl
from actions.delivery_summary import consolidate, identity, item_title
from storage import write_json

FILE = Path(__file__).resolve().parents[1] / 'data' / 'delivery_state.json'


@contextmanager
def locked_state():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load_state():
    try:
        state = json.loads(FILE.read_text(encoding='utf-8'))
        if isinstance(state, dict) and isinstance(state.get('items'), dict):
            return state
    except (OSError, ValueError):
        pass
    return {'items': {}}


def delivery_id(delivery):
    return hashlib.sha256(json.dumps(identity(delivery), default=str).encode()).hexdigest()


def record_deliveries(deliveries, carrier, expected):
    if isinstance(deliveries, dict):
        deliveries = [deliveries]
    rows = consolidate([row for row in (deliveries or []) if isinstance(row, dict)])
    with locked_state():
        state = load_state()
        pending = []
        for row in rows:
            key = delivery_id(row)
            old = state['items'].get(key, {})
            state['items'][key] = {'id': key, 'title': item_title(row) or carrier(row),
                                   'carrier': carrier(row), 'expected': expected(row),
                                   'date': str(row.get('delivery_date') or ''),
                                   'confirmed': bool(old.get('confirmed'))}
            if not state['items'][key]['confirmed']:
                pending.append(row)
        write_json(FILE, state)
    return pending


def checklist():
    items = [row for row in load_state()['items'].values() if isinstance(row, dict)]
    # Normalise existing cached labels too; retain IDs and confirmation state.
    items = [dict(row, **{field:unescape(str(row.get(field) or '')) for field in ('title','carrier','expected')}) for row in items]
    return sorted(items, key=lambda row: (bool(row.get('confirmed')), row.get('date', ''), row.get('title', '')))


def confirm_delivery(key, confirmed):
    with locked_state():
        state = load_state()
        if key not in state['items']:
            return False
        state['items'][key]['confirmed'] = confirmed
        write_json(FILE, state)
    return True
