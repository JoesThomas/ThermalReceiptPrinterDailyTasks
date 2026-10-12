"""Private daily print outcomes, kept separately from the latest manual print."""

from datetime import date, datetime, timezone
from pathlib import Path
import os
from storage import PrivateStore
from receipt.local_time import UK, uk_now, local_run
from web_control.job_runtime import MAX_SECONDS

ROOT = Path(__file__).resolve().parents[1]
STATES = {
    "starting",
    "launched",
    "running",
    "sent",
    "saved_preview",
    "failed",
    "timed_out",
    "cancelled",
    "launch_failed",
}
LABELS = {
    "starting": "Starting daily receipt",
    "launched": "Daily receipt launched; outcome pending",
    "running": "Daily receipt running",
    "sent": "Sent to printer; paper output not confirmed",
    "saved_preview": "Preview saved; physical printing paused",
    "failed": "Daily print failed",
    "timed_out": "Daily print timed out",
    "cancelled": "Daily print cancelled",
    "launch_failed": "Daily receipt could not launch",
    "missed": "Daily print missed; no scheduled job recorded",
    "not_due": "Daily print is not due yet",
    "disabled": "Automatic printing is disabled",
    "interrupted": "Daily receipt interrupted; no completed outcome recorded",
    "legacy": "Daily job launched; outcome unavailable for this older record",
}


def validate(value):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("days"), dict)
        or len(value["days"]) > 90
    ):
        raise ValueError("Invalid daily print history.")
    for on, row in value["days"].items():
        date.fromisoformat(on)
        if not isinstance(row, dict) or row.get("state") not in STATES:
            raise ValueError("Invalid daily print outcome.")
        datetime.fromisoformat(row["updated_at"])
        if (
            row.get("preview_saved") is not None
            and type(row["preview_saved"]) is not bool
        ):
            raise ValueError("Invalid saved-preview status.")


def store(directory=None):
    directory = Path(directory) if directory is not None else ROOT / "data"
    return PrivateStore(
        directory / "scheduled_print_history.json",
        default=lambda: {"days": {}},
        validate=validate,
        schema_version=1,
        migrations={0: lambda value: value},
        max_bytes=100000,
    )


def record(
    on, state, *, directory=None, job_id=None, worker_pid=None, preview_saved=None
):
    def change(value):
        key = on.isoformat()
        previous = value["days"].get(key, {})
        # A fast worker may finish before the parent records its successful launch.
        if state == "launched" and previous.get("state") not in {
            "starting",
            "launch_failed",
            None,
        }:
            return
        row = dict(
            previous, state=state, updated_at=datetime.now(timezone.utc).isoformat()
        )
        if state == "starting":
            row = {"state": state, "updated_at": row["updated_at"]}
        if job_id is not None:
            row["job_id"] = job_id
        if worker_pid is not None:
            row["worker_pid"] = worker_pid
        if preview_saved is not None:
            row["preview_saved"] = preview_saved
        value["days"][key] = row
        value["days"] = dict(sorted(value["days"].items(), reverse=True)[:90])

    return store(directory).update(change)


def pending_day(directory, now=None):
    now = now or uk_now()
    rows = store(directory).read()["days"]
    for on, row in sorted(rows.items(), reverse=True):
        parsed = datetime.fromisoformat(row["updated_at"])
        age = (now - parsed).total_seconds() if parsed.tzinfo else float("inf")
        if row["state"] in {"starting", "launched"} and 0 <= age <= 90:
            return date.fromisoformat(on)
    return now.astimezone(UK).date()


def display(row, now):
    state = row["state"]
    if state in {"starting", "launched", "running"}:
        stamp = datetime.fromisoformat(row["updated_at"])
        age = (now - stamp).total_seconds() if stamp.tzinfo else MAX_SECONDS + 31
        interrupted = age > MAX_SECONDS + 30
        pid = row.get("worker_pid")
        if type(pid) is int and pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                interrupted = True
            except (PermissionError, OSError):
                pass
        if interrupted:
            state = "interrupted"
    return dict(row, state=state, label=LABELS[state])


def summary(settings, *, now=None, directory=None, marker=None):
    now = (now or uk_now()).astimezone(UK)
    from web_control.scheduled_print import schedule_options

    enabled, hour, minute = schedule_options(settings)
    directory = Path(directory) if directory is not None else ROOT / "data"
    try:
        rows = store(directory).read()["days"]
    except (OSError, ValueError):
        return {
            "today": {
                "state": "unavailable",
                "label": "Daily print history unavailable; restore the private history file.",
            },
            "recent": [],
        }
    on = now.date().isoformat()
    if on in rows:
        today = display(rows[on], now)
    else:
        state = (
            "disabled"
            if not enabled
            else "missed"
            if now.timestamp() >= local_run(now.date(), hour, minute).timestamp()
            else "not_due"
        )
        marker = (
            Path(marker) if marker is not None else directory / ".scheduled_print_date"
        )
        try:
            if marker.read_text().strip() == on:
                state = "legacy"
        except OSError:
            pass
        today = {"state": state, "label": LABELS[state], "preview_saved": False}
    return {
        "date": on,
        "today": today,
        "recent": [
            dict(display(row, now), date=on)
            for on, row in sorted(rows.items(), reverse=True)[:7]
        ],
    }
