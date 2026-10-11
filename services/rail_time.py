"""UK rail timetable times shared by journey collectors."""

from datetime import datetime
from zoneinfo import ZoneInfo


def rail_time(on, text):
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None
    return datetime.combine(on, parsed, tzinfo=ZoneInfo("Europe/London"))
