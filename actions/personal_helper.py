"""Explainable local daily planning. No messages, calendar edits or live tracking."""

import math
from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from actions import checklists
from receipt.local_time import UK, uk_today
from services.day_travel import key as location_key
from services.day_travel import point, when
from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / "data" / "personal_helper.json"


def text(value, limit=160, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
        or (not empty and not value.strip())
    ):
        raise ValueError("Use a short, single-line label.")
    return value.strip()


def defaults():
    return dict(
        version=1,
        enabled=True,
        compact=True,
        show_task_times=False,
        receipt_priorities={},
        start="08:00",
        end="20:00",
        lighter=[],
        tasks={},
        rules=[],
        errands={},
        weather={},
        meal_uses={},
    )


def validate(s):
    if not isinstance(s, dict) or s.get("version") != 1:
        raise ValueError("Invalid personal helper settings.")
    for field in ("enabled", "compact"):
        if type(s[field]) is not bool:
            raise ValueError("Invalid helper setting.")
    if type(s.get("show_task_times", False)) is not bool:
        raise ValueError("Invalid receipt task-time setting.")
    priorities = s.get("receipt_priorities", {})
    if not isinstance(priorities, dict):
        raise ValueError("Invalid receipt priorities.")
    if priorities:
        date.fromisoformat(priorities["day"])
        ids = priorities["ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 3:
            raise ValueError("Choose up to three receipt priorities.")
        for identifier in ids:
            text(identifier, 128)
        if len(set(ids)) != len(ids):
            raise ValueError("Choose a different task for each position.")
    if time.fromisoformat(s["start"]) >= time.fromisoformat(s["end"]):
        raise ValueError("The planning day must finish after it starts.")
    if not isinstance(s["lighter"], list) or len(s["lighter"]) > 31:
        raise ValueError("Too many lighter-day entries.")
    for day in s["lighter"]:
        date.fromisoformat(day)
    if not isinstance(s["tasks"], dict) or len(s["tasks"]) > 500:
        raise ValueError("Too many helper tasks.")
    for identifier, m in s["tasks"].items():
        text(identifier, 128)
        if not isinstance(m, dict):
            raise ValueError("Invalid helper task metadata.")
        if m.get("minutes") is not None and (
            type(m["minutes"]) is not int or not 1 <= m["minutes"] <= 480
        ):
            raise ValueError("Task duration must be 1–480 minutes.")
        if m.get("context", "home") not in {"home", "anywhere", "outside"} or m.get(
            "effort", "normal"
        ) not in {"low", "normal", "high"}:
            raise ValueError("Invalid task context.")
        for field in ("essential", "hidden"):
            if type(m.get(field, False)) is not bool:
                raise ValueError("Invalid task flag.")
        for field in ("first_seen", "defer_until", "completed"):
            if m.get(field):
                date.fromisoformat(m[field])
        for day in m.get("deferrals", []):
            date.fromisoformat(day)
        if len(m.get("deferrals", [])) > 30 or len(m.get("steps", [])) > 10:
            raise ValueError("Too many task notes.")
        for step in m.get("steps", []):
            text(step, 160)
        if not isinstance(m.get("step_done", []), list) or any(
            type(i) is not int or not 0 <= i < len(m.get("steps", []))
            for i in m.get("step_done", [])
        ):
            raise ValueError("Invalid substep status.")
    if not isinstance(s["rules"], list) or len(s["rules"]) > 50:
        raise ValueError("Too many preparation rules.")
    for rule in s["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("Invalid preparation rule.")
        text(rule["id"], 32)
        text(rule["match"], 120)
        if type(rule["lead_hours"]) is not int or not 0 <= rule["lead_hours"] <= 72:
            raise ValueError("Preparation lead time must be 0–72 hours.")
        for field in ("take", "prepare"):
            if not isinstance(rule[field], list) or len(rule[field]) > 8:
                raise ValueError("Use at most eight short prompts.")
            for line in rule[field]:
                text(line, 120)
    if not isinstance(s["errands"], dict) or len(s["errands"]) > 50:
        raise ValueError("Too many errands.")
    for identifier, errand in s["errands"].items():
        text(identifier, 128)
        text(errand["address"], 500)
        if errand.get("point") is not None:
            point(errand["point"])
        text(errand.get("hours", ""), 160, empty=True)
    if (
        not isinstance(s.get("weather"), dict)
        or not isinstance(s.get("meal_uses"), dict)
        or len(s["meal_uses"]) > 1000
    ):
        raise ValueError("Invalid helper metadata.")
    weather = s["weather"]
    if weather:
        date.fromisoformat(weather["day"])
        for field, low, high in [("rain", 0, 100), ("low", -80, 60)]:
            value = weather.get(field)
            if value is not None and (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError("Invalid saved weather summary.")
    for quantity in s["meal_uses"].values():
        text(quantity, 80)


def store():
    return PrivateStore(FILE, default=defaults, validate=validate, max_bytes=1_000_000)


def observe(tasks, on=None):
    day = (on or uk_today()).isoformat()
    ids = {t["id"] for t in tasks if t["kind"] == "tasks"}

    def update(s):
        s["tasks"] = {k: v for k, v in s["tasks"].items() if k in ids}
        s["errands"] = {k: v for k, v in s["errands"].items() if k in ids}
        for row in tasks:
            if row["kind"] != "tasks":
                continue
            m = s["tasks"].setdefault(row["id"], {})
            m.setdefault("first_seen", day)
            if row.get("done_on") and row["done_on"] != m.get("completed"):
                m.update(completed=row["done_on"], deferrals=[])

    return store().update(update)


def weather_summary(raw):
    daily = raw.get("daily", {})
    days = daily.get("time", [])
    if not days:
        return {}
    rain = (daily.get("precipitation_probability_max") or [None])[0]
    low = (daily.get("temperature_2m_min") or [None])[0]
    return dict(
        day=str(days[0]),
        rain=rain
        if type(rain) in (int, float) and math.isfinite(rain) and 0 <= rain <= 100
        else None,
        low=low
        if type(low) in (int, float) and math.isfinite(low) and -80 <= low <= 60
        else None,
    )


def capture_weather(raw):
    summary = weather_summary(raw)
    if summary and store().read()["weather"] != summary:
        store().update(lambda s: s.update(weather=summary))


def stamp(raw):
    dt = when(raw)
    return dt.astimezone(UTC) if dt else None


def fresh_plan(plan, on, now):
    checked = stamp(plan.get("checked")) if isinstance(plan, dict) else None
    return bool(
        checked
        and plan.get("day") == on.isoformat()
        and 0 <= (now - checked).total_seconds() <= 86400
    )


def calendar_signature(events, on):
    return {
        (
            str(e.get("title", "")).strip(),
            str(stamp(e.get("start_dt") or e.get("start"))),
            str(stamp(e.get("end_dt") or e.get("end"))),
            str(e.get("location", e.get("address", "")) or "").strip(),
        )
        for e in events
        if (start := stamp(e.get("start_dt") or e.get("start")))
        and start.astimezone(UK).date() == on
    }


def windows(events, plan, s, now):
    on = now.astimezone(UK).date()
    start = max(
        now,
        datetime.combine(on, time.fromisoformat(s["start"]), UK).astimezone(UTC),
    )
    finish = datetime.combine(on, time.fromisoformat(s["end"]), UK).astimezone(UTC)
    busy = []
    transitions = []
    warnings = []
    for e in events:
        a = stamp(e.get("start_dt") or e.get("start"))
        b = stamp(e.get("end_dt") or e.get("end"))
        if not a or e.get("all_day") or a >= finish or (b and b <= start):
            continue
        address = e.get("location", e.get("address", "")) or ""
        if not b or b <= a:
            b = finish
            warnings.append(
                "Finish time unknown for "
                + str(e.get("title", "an event"))
                + "; later free time is not assumed."
            )
        busy.append((a, b))
        transitions.append(
            (
                b,
                0,
                "home"
                if not address or plan and location_key(address) == plan.get("home_id")
                else "outside",
            )
        )
        if address and not plan:
            busy.append((a - timedelta(minutes=30), a))
            transitions.append((a - timedelta(minutes=30), 0, "unknown"))
            warnings.append(
                "No current travel plan: a provisional 30-minute pre-event buffer is reserved; travel may need longer."
            )
    if plan:
        for leg in plan.get("legs", []):
            a = stamp(leg.get("depart"))
            b = stamp(leg.get("arrive"))
            if a and b and b >= a:
                busy.append((a, b))
                destination = leg.get("destination", {})
                transitions.append(
                    (
                        b,
                        1,
                        "home"
                        if destination.get("id") == plan.get("home_id")
                        else "outside",
                    )
                )
            else:
                warnings.append(
                    "Some travel times are unknown; free-time suggestions need review."
                )
    merged = []
    for a, b in sorted(busy):
        a = max(a, start)
        b = min(b, finish)
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    free = []
    cursor = start
    for a, b in merged + [(finish, finish)]:
        if a > cursor:
            context = "home"
            for t, _, place in sorted(transitions):
                if t <= cursor:
                    context = place
            free.append(
                dict(
                    start=cursor,
                    end=a,
                    minutes=int((a - cursor).total_seconds() // 60),
                    context=context,
                )
            )
        cursor = max(cursor, b)
    return free, warnings


def near_route(coords, geometry):
    if not coords or len(geometry) < 2:
        return None
    lat, lon = coords
    scale = 111000 * math.cos(math.radians(lat))
    best = float("inf")
    for a, b in zip(geometry, geometry[1:]):
        ax = (a[1] - lon) * scale
        ay = (a[0] - lat) * 111000
        bx = (b[1] - lon) * scale
        by = (b[0] - lat) * 111000
        length = (bx - ax) ** 2 + (by - ay) ** 2
        t = max(0, min(1, -(ax * (bx - ax) + ay * (by - ay)) / length)) if length else 0
        best = min(best, math.hypot(ax + t * (bx - ax), ay + t * (by - ay)))
    return best


def is_deferred(row, settings, day):
    meta = settings["tasks"].get(row["id"], {})
    due = row.get("due")
    return bool(meta.get("defer_until", "") > day
                and not meta.get("essential") and not (due and due <= day))


def build(tasks, events=None, travel_day=None, settings=None, now=None, *, pinned=()):
    s = deepcopy(settings if settings is not None else store().read())
    now = (now or datetime.now(UK)).astimezone(UTC)
    on = now.astimezone(UK).date()
    day = on.isoformat()
    light = day in s["lighter"]
    warnings = []
    travel_day = travel_day or {}
    plan = deepcopy(travel_day.get("plan") or {})
    if events is None:
        events = travel_day.get("events", [])
    if plan and not fresh_plan(plan, on, now):
        plan = {}
        warnings.append(
            "Saved travel plan is old or for another day; rebuild it for departure and errand prompts."
        )
    if (
        plan
        and travel_day.get("events")
        and calendar_signature(events, on)
        != calendar_signature(travel_day["events"], on)
    ):
        plan = {}
        warnings.append(
            "Calendar and travel plan differ; rebuild Day travel before relying on departure times."
        )
    if plan:
        warnings.extend(plan.get("warnings", []))
        home = next(
            (p for p in plan.get("points", []) if p.get("label") == "Home"), None
        )
        plan["home_id"] = home.get("id") if home else None
    free, notes = windows(events, plan, s, now)
    warnings.extend(notes)
    pending = []
    urgent = []
    nudges = []
    # Caller supplies actual tasks; no task mutations or planning network requests occur here.
    for row in tasks or []:
        if row.get("kind") != "tasks" or checklists.is_done(row, day):
            continue
        if row.get("shop_supplier") and not checklists.task_due(row, day):
            continue
        m = s["tasks"].get(row["id"], {})
        due = row.get("due", "")
        critical = bool(m.get("essential") or due and due <= day)
        item = dict(
            row,
            meta=m,
            critical=critical,
            minutes=m.get("minutes") or (5 if light else 10),
            timebox=m.get("minutes") is None,
            context=m.get("context", "home"),
        )
        next_step = next(
            (
                step
                for i, step in enumerate(m.get("steps", []))
                if i not in m.get("step_done", [])
            ),
            None,
        )
        item["next_step"] = next_step
        if critical:
            urgent.append(item)
        age = (on - date.fromisoformat(m.get("first_seen", day))).days
        if row.get("repeat", "none") == "none" and (
            len(set(m.get("deferrals", []))) >= 3 or age >= 7
        ):
            nudges.append(
                dict(
                    id=row["id"],
                    title=row["title"],
                    days=age,
                    deferrals=len(set(m.get("deferrals", []))),
                )
            )
        if (
            m.get("hidden")
            or is_deferred(row, s, day)
            or row.get("skipped_on") == day
        ):
            if not critical:
                continue
        if due and due > day and not critical:
            continue
        if light and not critical and m.get("effort") == "high":
            continue
        pending.append(item)

    def order(r):
        return (
            0
            if r["critical"]
            else 1
            if r["id"] in pinned
            else 2
            if r.get("priority") == "high"
            else 4
            if r.get("priority") == "low"
            else 3,
            r.get("due") or "9999",
            r["title"].casefold(),
        )

    pending.sort(key=order)
    urgent.sort(key=order)
    priority_limit = 2 if light else 3
    saved_order = s.get("receipt_priorities", {})
    if saved_order.get("day") == day:
        ranks = {identifier: i for i, identifier in enumerate(saved_order["ids"])}
        pending.sort(key=lambda row: ranks.get(row["id"], 3))

    reservations = []
    remaining = [dict(w) for w in free]
    for item in pending:
        for w in remaining:
            if item["context"] != "anywhere" and item["context"] != w["context"]:
                continue
            if w["minutes"] >= item["minutes"]:
                a = w["start"]
                b = a + timedelta(minutes=item["minutes"])
                reservations.append(
                    dict(
                        id=item["id"],
                        title=item["title"],
                        start=a,
                        end=b,
                        minutes=item["minutes"],
                        timebox=item["timebox"],
                        context=w["context"],
                    )
                )
                w["start"] = b
                w["minutes"] -= item["minutes"]
                break
        if len(reservations) >= 12:
            break
    departure = None
    if plan:
        for leg in plan.get("legs", []):
            a = stamp(leg.get("depart"))
            if a and a >= now:
                departure = dict(
                    at=a,
                    destination=leg.get("destination", {}).get("label", "Next stop"),
                    mode=leg.get("mode", ""),
                )
                break
    take = []
    preparation = []
    for e in events:
        start = stamp(e.get("start_dt") or e.get("start"))
        if not start or start < now:
            continue
        address = e.get("location", e.get("address", "")) or ""
        title = str(e.get("title", "Appointment"))
        for rule in s["rules"]:
            if rule["match"].casefold() not in title.casefold():
                continue
            if start.astimezone(UK).date() == on and address:
                take.extend(rule["take"])
            deadline = start - timedelta(hours=rule["lead_hours"])
            if deadline.astimezone(UK).date() <= on and start <= now + timedelta(
                hours=72
            ):
                preparation.extend(
                    dict(title=line, event=title, by=deadline, late=deadline < now)
                    for line in rule["prepare"]
                )
        if address and start.astimezone(UK).date() == on + timedelta(days=1):
            preparation.append(
                dict(
                    title="Charge your phone for tomorrow’s outing",
                    event=title,
                    by=datetime.combine(on, time(20), UK).astimezone(UTC),
                    late=False,
                )
            )
    outing = any(
        (e.get("location", e.get("address", "")) or "")
        and (a := stamp(e.get("start_dt") or e.get("start")))
        and a.astimezone(UK).date() == on
        and a >= now
        for e in events
    )
    if outing:
        take.append("Phone and keys")
        if s["weather"].get("day") == day:
            if s["weather"].get("rain") is not None and s["weather"]["rain"] >= 40:
                take.append("Umbrella / raincoat")
            if s["weather"].get("low") is not None and s["weather"]["low"] <= 8:
                take.append("Warm layer")
    errands = []
    if plan:
        geometry = []
        for leg in plan.get("legs", []):
            if (
                leg.get("mode") in {"walking", "cycling", "driving"}
                and (a := stamp(leg.get("depart")))
                and a >= now
            ):
                geometry.append(leg.get("geometry", []))
        for item in pending:
            errand = s["errands"].get(item["id"])
            if not errand or not errand.get("point"):
                continue
            distances = [
                d for g in geometry if (d := near_route(errand["point"], g)) is not None
            ]
            if distances and min(distances) <= 300:
                errands.append(
                    dict(
                        id=item["id"],
                        title=item["title"],
                        distance=int(round(min(distances) / 50) * 50),
                        hours=errand.get("hours") or "Opening hours not checked",
                        address=errand["address"],
                    )
                )
    # Deduplicate cross-event prompts and keep full detail in the web view.
    preparation = sorted(
        {(p["title"], p["by"]): p for p in preparation}.values(), key=lambda p: p["by"]
    )
    return dict(
        enabled=s["enabled"],
        compact=s["compact"],
        show_task_times=s.get("show_task_times", False),
        priority_limit=priority_limit,
        day=day,
        lighter=light,
        priorities=pending[:priority_limit],
        urgent=urgent,
        windows=free,
        reservations=reservations,
        departure=departure,
        take=list(dict.fromkeys(take)),
        preparation=preparation,
        errands=errands,
        nudges=nudges,
        warnings=list(dict.fromkeys(warnings)),
        pending=pending,
    )


def context(events=None, now=None, observe_tasks=False):
    lists = checklists.load()
    tasks = lists["items"]
    settings = (
        observe(tasks, (now or datetime.now(UK)).date())
        if observe_tasks
        else store().read()
    )
    from storage import read_json_object
    from web_control.today_summary import CALENDAR

    calendar_state = read_json_object(CALENDAR)
    supplied = events is not None
    if events is None:
        events = calendar_state.get("events", [])
    from services.day_travel import store as travel_store

    day = (now or datetime.now(UK)).astimezone(UK).date().isoformat()
    focus = lists.get("assistant", {}).get("focus", {})
    pinned = focus.get("ids", []) if focus.get("day") == day else []
    view = build(
        tasks,
        events,
        travel_store().read()["days"].get(day, {}),
        settings,
        now,
        pinned=pinned,
    )

    if not supplied:
        checked = stamp(calendar_state.get("checked_at"))
        current = (now or datetime.now(UK)).astimezone(UTC)
        if not checked or not 0 <= (current - checked).total_seconds() <= 86400:
            view["warnings"].append(
                "Calendar snapshot is not current; suggested gaps are provisional. Refresh Calendar or Day travel."
            )
    return view


def receipt_brief(view):
    if not view["enabled"]:
        return []
    lines = []
    if view["lighter"]:
        lines.append("LIGHTER DAY · essentials first")
    timed = view.get("show_task_times", False)
    slots = {r["id"]: r for r in view["reservations"]} if timed else {}
    for row in view["priorities"]:
        slot = slots.get(row["id"])
        prefix = (
            slot["start"].astimezone(UK).strftime("%H:%M") + " "
            if slot and not view["warnings"]
            else ""
        )
        action = "Start: " if prefix and row["timebox"] else ""
        lines.append(
            "[ ] "
            + prefix
            + action
            + row["title"]
            + (" · " + row["next_step"] if row.get("next_step") else "")
        )
    chosen = {r["id"] for r in view["priorities"]}
    extra = sum(r["id"] not in chosen for r in view["urgent"])
    if extra:
        lines.append(f"{extra} more deadline/essential item(s): check helper")
    if view["departure"]:
        lines.append(
            "Leave "
            + view["departure"]["at"].astimezone(UK).strftime("%H:%M")
            + " · "
            + view["departure"]["destination"]
        )
    notes = []
    if view["preparation"]:
        prep = view["preparation"][0]
        notes.append(
            "Prep "
            + (
                "now"
                if prep["late"]
                else "by " + prep["by"].astimezone(UK).strftime("%H:%M")
            )
            + ": "
            + prep["title"]
        )
    if view["take"]:
        notes.append("Take: " + ", ".join(view["take"][:4]))
    if view["errands"]:
        notes.append(
            "Near route: " + view["errands"][0]["title"] + " (check time/opening)"
        )
    lines.extend(notes[:2])
    return lines
