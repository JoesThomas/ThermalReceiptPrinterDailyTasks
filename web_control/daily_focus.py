"""Prioritise locally known actions and explain why each is relevant today."""

from datetime import date, datetime
from receipt.local_time import UK


def build(today, tasks, assistant, bins, vehicles, birthdays, finance):
    items = []

    def add(rank, title, why, endpoint):
        items.append(dict(rank=rank, title=title, why=why, endpoint=endpoint))

    for line in bins:
        if "Put out" in line:
            add(
                0,
                line.replace("[ ] ", ""),
                "Collection is tomorrow; put the bin out today.",
                "bin_settings",
            )
    for vehicle in vehicles:
        expiry = vehicle.get("mot_expiry")
        if expiry and (days := (date.fromisoformat(expiry) - today).days) <= 30:
            add(
                0 if days <= 7 else 2,
                "Book/check MOT · " + vehicle["registration"],
                f"Recorded MOT expiry {expiry}; {'overdue' if days < 0 else str(days) + ' days away'}. Booking tasks start at 30 days.",
                "vehicle_list",
            )
    for item in birthdays:
        if item["date"] == today.isoformat():
            add(
                1,
                "Birthday today · " + item["name"],
                "Their saved birthday falls today.",
                "birthday_list",
            )
    if assistant.get("appointment"):
        add(
            1,
            assistant["appointment"]["lines"][0],
            "Next appointment in today’s saved calendar; review preparation and travel time.",
            "calendar_map",
        )
    current = (finance or {}).get("current") or {}
    stamp = (finance or {}).get("checked_at", "")
    try:
        checked_today = datetime.fromisoformat(stamp).astimezone(UK).date() == today
    except (ValueError, TypeError):
        checked_today = False
    if current.get("valid") and current.get("shortfall") and checked_today:
        due = date.fromisoformat(current["shortfall"])
        if (due - today).days <= 30:
            add(
                1,
                "Review upcoming cash shortfall",
                f"The last complete check projects a reserve shortfall on {due:%d %b}; refresh Finance before acting.",
                "finance_review",
            )
    chosen = {r["id"] for r in assistant.get("focus", [])}
    for task in assistant.get("focus", []) + tasks:
        if task["title"].startswith("Book MOT for ") and any(
            v["registration"] in task["title"] for v in vehicles
        ):
            continue
        if task.get("due") or task["id"] in chosen:
            why = (
                "Chosen as one of your priorities today."
                if task["id"] in chosen
                else "Task due " + task["due"] + "."
            )
            add(2 if task["id"] in chosen else 3, task["title"], why, "task_list")
    return sorted(items, key=lambda r: (r["rank"], r["title"]))[:8]
