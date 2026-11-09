"""Keep one dated checklist task per scheduled butcher or greengrocer visit."""

from datetime import date
from hashlib import sha256

from actions import checklists
from meals import monthly
from receipt.local_time import uk_today

SUPPLIERS = {
    "Butcher": "Buy meat from the butcher",
    "Greengrocer": "Shop at the greengrocer",
}


def needs_sync(state, raw, on):
    if raw not in state.get("shopping_task_months", []):
        return True
    return any(
        row.get("shop_month") == raw and not row["done"]
        and ((due := date.fromisoformat(row["shop_day"])) < on or due.weekday() < 5)
        for row in state["items"] if row.get("shop_day")
    )


def sync(raw, on=None, *, first_only=False):
    on = on or uk_today()
    if monthly.bounds(raw)[1] < on:
        return
    if first_only and not needs_sync(checklists.load(), raw, on):
        return
    view = monthly.report(raw, on)
    scheduled = {}
    for visit in view["visits"]:
        supplier = visit["shop"]
        if supplier not in SUPPLIERS:
            continue
        day = visit["day"].isoformat()
        if not any(need >= day for item in visit["items"] for need in item["needs"]):
            continue  # The visit only contains missed meal needs, not an actionable shop.
        key = sha256(f"meal-shopping:{raw}:{day}:{supplier}".encode()).hexdigest()
        scheduled[key] = dict(
            id=key,
            kind="tasks",
            source="local",
            title=SUPPLIERS[supplier],
            done=False,
            done_on=None,
            due=day,
            shop_day=day,
            shop_month=raw,
            shop_supplier=supplier,
        )
    with checklists.transaction() as state:
        months = state.get("shopping_task_months", [])
        if first_only and not needs_sync(state, raw, on):
            return
        state["items"] = [
            row
            for row in state["items"]
            if row.get("shop_month") != raw or row["done"] or row["id"] in scheduled
        ]
        existing = {row["id"] for row in state["items"]}
        additions = [row for key, row in scheduled.items() if key not in existing]
        if additions and len(state["items"]) + len(additions) > 500:
            raise ValueError("The task list is full.")
        state["items"].extend(additions)
        state["shopping_task_months"] = sorted({raw, *months})[-24:]


def ensure():
    """Replace outdated pending shop tasks while retaining completed history."""
    if not monthly.FILE.exists():
        return
    active = monthly.store().read()["active_month"]
    state = checklists.load()
    on = uk_today()
    months = set(state.get("shopping_task_months", []))
    if active:
        months.add(active)
    for raw in sorted(months):
        if monthly.bounds(raw)[1] >= on and needs_sync(state, raw, on):
            sync(raw, on, first_only=True)
