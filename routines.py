from __future__ import annotations
import json
from datetime import date, datetime, timedelta
from config import TIMEZONE
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent
ROUTINES_FILE = PROJECT_ROOT / "data" / "routines.json"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

def load_routines():
    if not ROUTINES_FILE.exists(): return []
    try: data = json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return []
    return data if isinstance(data, list) else []

def save_routines(routines):
    from storage import write_json
    write_json(ROUTINES_FILE, routines)


def add_routine(name, schedule_type, *, weekday=None, interval_days=None, show_days_before=0, enabled=True):
    name = str(name).strip()
    if not name or len(name) > 160 or any(ord(c) < 32 for c in name):
        raise ValueError('Enter a routine name up to 160 characters.')
    if schedule_type not in {'weekly', 'interval'} or (schedule_type == 'weekly' and weekday not in WEEKDAYS):
        raise ValueError('Choose a valid routine schedule.')
    if schedule_type == 'interval' and (interval_days is None or not 1 <= int(interval_days) <= 36500):
        raise ValueError('Choose an interval of 1 to 36500 days.')
    if not 0 <= int(show_days_before) <= 36500:
        raise ValueError('Choose a valid reminder period.')
    routines = load_routines()
    item = {"id": uuid4().hex, "name": str(name).strip(), "enabled": bool(enabled), "schedule_type": schedule_type,
            "weekday": weekday, "interval_days": interval_days, "show_days_before": max(0, int(show_days_before or 0)),
            "start_date": datetime.now(TIMEZONE).date().isoformat(), "last_completed": None}
    routines.append(item); save_routines(routines); return item

def _as_date(value):
    try: return date.fromisoformat(str(value)) if value else None
    except ValueError: return None

def next_due_date(routine, today=None):
    today = today or datetime.now(TIMEZONE).date(); kind = routine.get("schedule_type")
    if kind == "weekly":
        weekday = str(routine.get("weekday") or "").lower()
        if weekday not in WEEKDAYS: return None
        return today + timedelta(days=(WEEKDAYS.index(weekday) - today.weekday()) % 7)
    if kind == "interval":
        try: days = max(1, int(routine.get("interval_days") or 1))
        except (TypeError, ValueError): return None
        last = _as_date(routine.get("last_completed"))
        return (last + timedelta(days=days)) if last else (_as_date(routine.get("start_date")) or today)
    return None

def routine_is_visible(routine, today=None):
    if not routine.get("enabled", True): return False
    today = today or datetime.now(TIMEZONE).date(); due = next_due_date(routine, today)
    if not due: return False
    try: before = max(0, int(routine.get("show_days_before") or 0))
    except (TypeError, ValueError): before = 0
    return today >= due - timedelta(days=before)

def due_routines(today=None):
    today = today or datetime.now(TIMEZONE).date(); output = []
    for routine in load_routines():
        if routine_is_visible(routine, today):
            item = dict(routine); item["next_due"] = next_due_date(routine, today).isoformat(); output.append(item)
    return output

def mark_done(routine_id, completed_on=None):
    routines = load_routines(); completed_on = completed_on or datetime.now(TIMEZONE).date()
    for item in routines:
        if item.get("id") == routine_id:
            item["last_completed"] = completed_on.isoformat(); save_routines(routines); return True
    return False

def delete_routine(routine_id):
    routines = load_routines(); new = [x for x in routines if x.get("id") != routine_id]
    if len(new) == len(routines): return False
    save_routines(new); return True

def set_enabled(routine_id, enabled):
    routines = load_routines()
    for item in routines:
        if item.get("id") == routine_id:
            item["enabled"] = bool(enabled); save_routines(routines); return True
    return False
