"""Per-generation source checks. A check timestamp is not a forecast's observation time."""
from datetime import datetime, timezone
_current = {}

def reset():
    _current.clear()

def mark(name, status='checked'):
    _current[name] = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': status}

def snapshot():
    return {name: dict(value) for name, value in _current.items()}
