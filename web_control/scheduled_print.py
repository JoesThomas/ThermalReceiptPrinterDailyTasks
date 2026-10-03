"""Print once a day at the configured UK time while Waitress runs."""
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


def schedule_options(settings=None):
    from receipt_settings import load_receipt_settings
    config = (settings if settings is not None else load_receipt_settings()).get('print_schedule', {})
    if not isinstance(config, dict):
        config = {}
    try:
        hour, minute = map(int, config.get('time', '03:00').split(':'))
        time(hour, minute)
    except (AttributeError, TypeError, ValueError):
        hour, minute = 3, 0
    return bool(config.get('enabled', True)), hour, minute


def _local_run(day, hour, minute):
    # Choose the first occurrence when clocks repeat; move to the first valid
    # minute when the configured time falls in the spring clock-change gap.
    from datetime import timezone
    candidate = datetime.combine(day, time(hour, minute), tzinfo=UK)
    while candidate.astimezone(timezone.utc).astimezone(UK).replace(tzinfo=None) != candidate.replace(tzinfo=None):
        candidate += timedelta(minutes=1)
    return candidate


def next_print_time(now, settings=None):
    enabled, hour, minute = schedule_options(settings)
    if not enabled:
        return None
    local = now.astimezone(UK)
    candidate = _local_run(local.date(), hour, minute)
    if local.timestamp() >= candidate.timestamp():
        candidate = _local_run(local.date() + timedelta(days=1), hour, minute)
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
    signature, due, retry_at = None, None, 0
    while not stop.is_set():
        now = now_fn()
        config = schedule_options()
        if config != signature:
            signature = config
            due = next_print_time(now)
            retry_at = 0
        if due is not None and now.timestamp() >= due.timestamp():
            if now.astimezone(UK).date() != due.date():
                due = next_print_time(now)
            elif now.timestamp() >= retry_at:
                try:
                    launched = print_once(due.date(), start_print, marker)
                except Exception:
                    LOG.exception('Scheduled receipt could not start')
                    launched = False
                if launched:
                    due = next_print_time(now)
                else:
                    retry_at = now.timestamp() + 300
        stop.wait(30)


def start_scheduler(start_print):
    thread = Thread(target=schedule_loop, args=(start_print, Event()),
                    name="receipt-daily-print", daemon=True)
    thread.start()
    return thread
