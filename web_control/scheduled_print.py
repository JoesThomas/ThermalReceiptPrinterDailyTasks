"""Print the full receipt once a day at 03:00 in the UK while Waitress runs."""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Event, Thread
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LAST_PRINT_DATE = ROOT / "data" / ".scheduled_print_date"
UK = ZoneInfo("Europe/London")
LOG = logging.getLogger(__name__)


def next_print_time(now):
    local = now.astimezone(UK)
    candidate = datetime.combine(local.date(), time(3), tzinfo=UK)
    if local >= candidate:
        candidate = datetime.combine(local.date() + timedelta(days=1), time(3), tzinfo=UK)
    return candidate


def print_once(today, start_print, marker=LAST_PRINT_DATE):
    """Record the local date only after a job has actually been launched."""
    try:
        if marker.read_text(encoding="ascii").strip() == today.isoformat():
            return True
    except FileNotFoundError:
        pass
    started, error = start_print([])
    if not started:
        LOG.warning("Scheduled receipt not started: %s", error)
        return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(marker.name + ".tmp")
    temporary.write_text(today.isoformat() + "\n", encoding="ascii")
    temporary.replace(marker)
    LOG.info("Scheduled receipt started for %s", today)
    return True


def schedule_loop(start_print, stop, now_fn=None, marker=LAST_PRINT_DATE):
    now_fn = now_fn or (lambda: datetime.now(UK))
    while not stop.is_set():
        due = next_print_time(now_fn())
        # Recheck the clock regularly, including across daylight saving changes.
        while not stop.is_set():
            remaining = (due.timestamp() - now_fn().timestamp())
            if remaining <= 0:
                break
            stop.wait(min(remaining, 60))
        if stop.is_set():
            return
        today = due.date()
        while not stop.is_set() and now_fn().astimezone(UK).date() == today:
            try:
                if print_once(today, start_print, marker):
                    break
            except Exception:
                LOG.exception("Scheduled receipt could not start")
            stop.wait(5 * 60)


def start_scheduler(start_print):
    thread = Thread(target=schedule_loop, args=(start_print, Event()),
                    name="receipt-daily-print", daemon=True)
    thread.start()
    return thread
