"""Private, manually maintained vehicle expiry records; no remote lookups."""

import re
import json
import hashlib
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from receipt.local_time import uk_today
from storage import file_lock, write_json

FILE = Path(__file__).resolve().parents[1] / "data" / "vehicles.json"
DATES = {
    "mot_expiry": "MOT",
    "tax_due": "Tax",
    "insurance_expiry": "Insurance",
    "breakdown_expiry": "Breakdown",
}
DETAILS = {
    "insurance_provider": "Insurance provider",
    "insurance_reference": "Insurance reference",
    "breakdown_provider": "Breakdown provider",
    "breakdown_reference": "Breakdown reference",
    "notes": "Notes",
}


def text(value, limit=160):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"Use one line of text, up to {limit} characters.")
    return value.strip()


def record(values, key=""):
    registration = text(values.get("registration", ""), 20).upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z0-9]{2,15}", registration):
        raise ValueError("Enter a registration using 2–15 letters or numbers.")
    key = key or uuid4().hex
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("Invalid vehicle record ID.")
    row = dict(id=key, registration=registration, name=text(values.get("name", ""), 80))
    for field in DATES:
        value = text(values.get(field, ""), 10)
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise ValueError(
                    f"Enter a real {DATES[field]} date in YYYY-MM-DD format."
                ) from None
        row[field] = value
    for field in DETAILS:
        row[field] = text(values.get(field, ""))
    return row


def validate(state):
    if (
        not isinstance(state, dict)
        or set(state) != {"version", "vehicles"}
        or type(state["version"]) is not int
        or state["version"] != 1
    ):
        raise ValueError("Unsupported vehicle records format.")
    rows = state["vehicles"]
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError("Save up to 20 vehicles.")
    ids, registrations = set(), set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not row.get("id")
            or record(row, row["id"]) != row
        ):
            raise ValueError("Invalid vehicle record.")
        if row["id"] in ids or row["registration"] in registrations:
            raise ValueError(
                "Vehicle registration already exists; edit its saved record."
            )
        ids.add(row["id"])
        registrations.add(row["registration"])
    return state


def load(path=None):
    try:
        with (Path(path) if path is not None else FILE).open("rb") as stream:
            raw = stream.read(256_001)
    except FileNotFoundError:
        return {"version": 1, "vehicles": []}
    if len(raw) > 256_000:
        raise ValueError("Vehicle records exceed the size limit.")
    try:
        return validate(json.loads(raw))
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError(
            "Saved vehicle records are invalid. Repair them before editing."
        ) from None


def update(values, key="", remove=False):
    with file_lock(FILE):
        state = load()
        if key and key not in {row["id"] for row in state["vehicles"]}:
            raise ValueError("Vehicle changed; refresh before editing.")
        if remove and not key:
            raise ValueError("Choose a vehicle to remove.")
        rows = [row for row in state["vehicles"] if row["id"] != key]
        if not remove:
            rows.append(record(values, key))
        result = validate({"version": 1, "vehicles": rows})
        write_json(FILE, result)
        return result


def expiry_label(value, today=None):
    if not value:
        return "Not recorded"
    today = today or uk_today()
    stamp = date.fromisoformat(value)
    remaining = (stamp - today).days
    label = stamp.strftime("%d %b %Y")
    unit = "day" if abs(remaining) == 1 else "days"
    if remaining < 0:
        return f"{label} - {abs(remaining)} {unit} past recorded date"
    if remaining == 0:
        return f"{label} - due today"
    if remaining <= 31:
        return f"{label} - in {remaining} {unit}"
    return label


def receipt_lines(rows=None, today=None):
    today = today or uk_today()
    rows = (
        load()["vehicles"]
        if rows is None
        else validate({"version": 1, "vehicles": rows})["vehicles"]
    )
    lines = []
    for row in rows:
        if today.weekday() != 6 and not any(
            row[field] and (date.fromisoformat(row[field]) - today).days in {30, 14, 7}
            for field in DATES
        ):
            continue
        if lines:
            lines.append("")
        lines.append((row["name"] + " - " if row["name"] else "") + row["registration"])
        for field, label in DATES.items():
            lines.append(f"{label}: {expiry_label(row[field], today)}")
        for field, label in DETAILS.items():
            if row[field]:
                lines.append(f"{label}: {row[field]}")
    return lines


def sync_mot_tasks(today=None, root=None):
    """Add one local booking task per registration/expiry cycle, including catch-up."""
    from actions import checklists

    today = today or uk_today()
    vehicle_path = Path(root) / "data" / "vehicles.json" if root is not None else None
    rows = load(vehicle_path)["vehicles"]
    eligible = [
        row
        for row in rows
        if row["mot_expiry"]
        and (date.fromisoformat(row["mot_expiry"]) - today).days <= 30
    ]
    if not eligible:
        return 0
    target = (
        Path(root) / "data" / "daily_lists.json"
        if root is not None
        else checklists.FILE
    )
    with file_lock(target):
        try:
            with target.open("rb") as stream:
                raw = stream.read(900_001)
            if len(raw) > 900_000:
                raise ValueError("Saved checklist exceeds the size limit.")
            state = checklists.validate_state(json.loads(raw))
        except FileNotFoundError:
            state = {"items": []}
        except (UnicodeError, ValueError, RecursionError):
            raise ValueError(
                "Saved checklist could not be read; restore it before adding MOT tasks."
            ) from None
        history = state.get("mot_task_keys", [])
        seen = set(history) | {item["id"] for item in state["items"]}
        added = 0
        for row in eligible:
            key = hashlib.sha256(
                (row["registration"] + ":" + row["mot_expiry"]).encode()
            ).hexdigest()
            if key in seen:
                continue
            if len(state["items"]) >= 500 or len(history) >= 2000:
                raise ValueError(
                    "The task list is full. Remove old tasks before adding MOT reminders."
                )
            title = f"Book MOT for {row['registration']}"
            if row["name"]:
                title += f" ({row['name']})"
            title += f" - expires {date.fromisoformat(row['mot_expiry']):%d %b %Y}"
            state["items"].append(
                dict(
                    id=key,
                    kind="tasks",
                    source="local",
                    title=title,
                    done=False,
                    done_on=None,
                    repeat="none",
                    priority="normal",
                    due=(
                        date.fromisoformat(row["mot_expiry"]) - timedelta(days=30)
                    ).isoformat(),
                )
            )
            history.append(key)
            seen.add(key)
            added += 1
        if added:
            state["mot_task_keys"] = history
            checklists.validate_state(state)
            write_json(target, state)
    return added
