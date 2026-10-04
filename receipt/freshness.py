"""Per-generation source checks. A check timestamp is not a forecast's observation time."""
from datetime import datetime, timezone
_current = {}

def reset():
    _current.clear()

def mark(name, status='checked', **metadata):
    from domain_models import SourceObservation
    observation=SourceObservation(name,status,datetime.now(timezone.utc).isoformat())
    _current[name] = {'checked_at': observation.checked_at, 'status': status, 'state':observation.state.value, **metadata}
    from services.api_health import record
    from services.source_status import health
    record(name,health(status))

def snapshot():
    return {name: dict(value) for name, value in _current.items()}
