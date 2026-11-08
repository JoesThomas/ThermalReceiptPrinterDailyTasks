"""Seven-day view of saved information. Never refresh external services here."""
from datetime import date, timedelta

from actions.day_assistant import event_start
from finance.bill_payments import posted_date
from finance.bill_payments import monthly_contract_ended
from receipt.local_time import uk_today


def review(today=None, events=None, *, actions_only=False):
    from organiser import records
    from web_control.today_summary import CALENDAR
    from storage import read_json_object
    from finance.receipt import load_finance_settings
    from finance.projection import payment_schedule
    from services.subscriptions import load_subscriptions
    from services import vehicle_records
    from meals import monthly
    from receipt_settings import load_receipt_settings

    today = today or uk_today()
    end = today + timedelta(days=6)
    rows, actions, warnings = [], [], []
    calendar = read_json_object(CALENDAR)
    if events is None:
        events = calendar.get("events", [])
    events = [row for row in (events or []) if isinstance(row, dict)]
    try:
        covered = (date.fromisoformat(calendar.get("coverage_from", "")) <= today
                   and date.fromisoformat(calendar.get("coverage_to", "")) >= end
                   and calendar.get("status") in {"checked", "live", "fresh"})
    except (ValueError, TypeError):
        covered = False
    if not covered:
        warnings.append("The saved calendar may not cover the full week. Refresh Calendar before relying on gaps.")
    for row in events:
        start = event_start(row)
        day = start.date() if start else posted_date(row.get("date"))
        if day and today <= day <= end:
            note = start.strftime("%H:%M") if start else ("All day" if row.get("all_day") else "")
            rows.append(dict(day=day, kind="Appointment", title=row.get("title") or "Appointment",
                             note=note, endpoint="calendar_map"))
    try:
        organiser = records.store().read()
        for row in organiser["items"]:
            due = date.fromisoformat(row["due"])
            if not row["done"] and due <= end:
                rows.append(dict(day=due, kind="Follow-up", title=row["title"], endpoint="organiser_page"))
        for offset in range(7):
            day = today + timedelta(days=offset)
            actions.extend(dict(day=day, title=message, endpoint="calendar_map")
                           for message in records.clashes(events, organiser["travel_buffer"], day))
    except (ValueError, OSError):
        warnings.append("Organiser follow-ups are unavailable.")
    try:
        for vehicle in vehicle_records.load()["vehicles"]:
            for field, label in vehicle_records.DATES.items():
                if vehicle.get(field) and today <= (due := date.fromisoformat(vehicle[field])) <= end:
                    title = f"{vehicle['name'] or vehicle['registration']}: {label} due"
                    rows.append(dict(day=due, kind="Renewal", title=title, endpoint="vehicle_list"))
                    actions.append(dict(day=due, title=title, endpoint="vehicle_list"))
    except (ValueError, OSError):
        warnings.append("Vehicle renewals are unavailable.")
    if not actions_only:
        try:
            data = load_subscriptions()
            settings = load_finance_settings()
            configured = [row for row in data["monthly"] if not monthly_contract_ended(row, today)]
            events_due, _, _ = payment_schedule(configured, data["yearly"], [], settings, today, horizon=6)
            for bill in events_due:
                if not bill["undated"]:
                    rows.append(dict(day=bill["date"], kind="Bill", title=bill["name"],
                                     note=f"£{bill['amount']:,.2f} · {bill['basis']}", endpoint="finance_review"))
        except (ValueError, OSError, TypeError):
            warnings.append("Scheduled bills are unavailable.")
    if load_receipt_settings()["features"].get("meals", True):
        try:
            from meals.shopping_tasks import SUPPLIERS
            from actions.checklists import load
            for row in load()["items"]:
                if row.get("shop_supplier") in SUPPLIERS and not row["done"]:
                    day = date.fromisoformat(row["shop_day"])
                    if not today <= day <= end:
                        continue
                    args = dict(month=row["shop_month"], supplier=row["shop_supplier"], day=day.isoformat())
                    rows.append(dict(day=day, kind="Shopping", title=row["title"], endpoint="meal_shop", args=args))
                    if any(r["day"] == day and r["kind"] == "Appointment" for r in rows):
                        actions.append(dict(day=day, title=f"{row['shop_supplier']} trip and appointment on the same day. Check timing.",
                                            endpoint="meal_shop", args=args))
            # Supermarket visits are derived from the saved menu; there is no task for these.
            months = set() if actions_only else {today.strftime("%Y-%m"), end.strftime("%Y-%m")}
            for raw in sorted(months):
                if not monthly.FILE.exists():
                    break
                visits = monthly.report(raw, today)["visits"]
                for day in sorted({visit["day"] for visit in visits if visit["shop"] in monthly.SUPERMARKET_SHOPS}):
                    if today <= day <= end and not any(r["kind"] == "Shopping" and r["day"] == day and r["title"] == "Supermarket shop" for r in rows):
                        rows.append(dict(day=day, kind="Shopping", title="Supermarket shop", endpoint="meal_shop",
                                         args={"month": raw, "day": day.isoformat()}))
        except (ValueError, OSError, KeyError, TypeError):
            warnings.append("Shopping plans are unavailable.")
    for row in sorted((r for r in rows if r["kind"] == "Follow-up"), key=lambda r: r["day"]):
        actions.append(dict(day=row["day"], title=row["title"], endpoint=row["endpoint"]))
    return dict(today=today, end=end, rows=sorted(rows, key=lambda r: (r["day"], r["kind"], r["title"])),
                actions=sorted(actions, key=lambda r: r["day"]), warnings=warnings)
