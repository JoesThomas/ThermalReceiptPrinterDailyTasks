"""Keep one dated checklist task per scheduled butcher or greengrocer visit."""

from hashlib import sha256

from actions import checklists
from meals import monthly
from receipt.local_time import uk_today

SUPPLIERS = {
    "Butcher": "Buy meat from the butcher",
    "Greengrocer": "Shop at the greengrocer",
}


def sync(raw, on=None, *, first_only=False):
    on = on or uk_today()
    if monthly.bounds(raw)[1] < on:
        return
    if first_only and raw in checklists.load().get("shopping_task_months", []):
        return
    view = monthly.report(raw, on)
    if not any(row["meal"] for row in view["days"]):
        return
    scheduled = {}
    for visit in view["visits"]:
        supplier = visit["shop"]
        if supplier not in SUPPLIERS:
            continue
        day = visit["day"].isoformat()
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
        if first_only and raw in months:
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
    """Initialise tasks for the saved active month after an application update."""
    if monthly.FILE.exists():
        raw = monthly.store().read()["active_month"]
        if raw:
            sync(raw, first_only=True)
