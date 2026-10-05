"""Presentation of saved UTC receipt times in the UK timezone."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def uk_receipt_time(value):
    if not value:
        return ""
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(ZoneInfo("Europe/London")).strftime("%d %b %Y, %H:%M %Z")
    except (ValueError, TypeError):
        return ""


def uk_now():
    return datetime.now(ZoneInfo("Europe/London"))


def uk_today():
    return uk_now().date()
