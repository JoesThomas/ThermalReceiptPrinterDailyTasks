"""Presentation of saved UTC receipt times in the UK timezone."""
from datetime import datetime, timezone, time, timedelta
from config import TIMEZONE as UK


def uk_receipt_time(value):
    if not value:
        return ""
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(UK).strftime("%d %b %Y, %H:%M %Z")
    except (ValueError, TypeError):
        return ""


def uk_now():
    return datetime.now(UK)


def uk_today():
    return uk_now().date()


def local_run(day, hour, minute):
    """First occurrence in autumn; first valid minute in the spring gap."""
    candidate = datetime.combine(day, time(hour, minute), tzinfo=UK)
    while candidate.astimezone(timezone.utc).astimezone(UK).replace(tzinfo=None) != candidate.replace(tzinfo=None):
        candidate += timedelta(minutes=1)
    return candidate
