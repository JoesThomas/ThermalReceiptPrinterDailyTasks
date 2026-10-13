"""Small daily prompts from chosen tasks and explicitly configured preparation."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from actions import checklists

UK = ZoneInfo("Europe/London")


def defaults():
    return dict(focus={"day": "", "ids": []}, appointments=[], bedtime=[])


def text(value, maximum=240):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Enter a short, single-line instruction.")
    return value.strip()


def instructions(value):
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("Choose up to five preparation instructions.")
    return [text(line, 160) for line in value]


def validate(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid daily assistant settings.")
    for key in ("focus", "other_focus"):
        focus = value.get(key, {})
        if not isinstance(focus, dict) or not isinstance(focus.get("day", ""), str):
            raise ValueError("Invalid daily priorities.")
        if focus.get("day"):
            date.fromisoformat(focus["day"])
        ids = focus.get("ids", [])
        if (
            not isinstance(ids, list)
            or len(ids) > 3
            or any(not isinstance(key, str) for key in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("Choose up to three distinct tasks.")
    rules = value.get("appointments", [])
    if not isinstance(rules, list) or len(rules) > 50:
        raise ValueError("Choose up to 50 appointment preparation rules.")
    titles = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("Invalid appointment preparation.")
        title = text(rule.get("title")).casefold()
        if title in titles:
            raise ValueError("Duplicate appointment preparation.")
        titles.add(title)
        minutes = rule.get("travel_minutes")
        if minutes is not None and (
            type(minutes) is not int or not 1 <= minutes <= 240
        ):
            raise ValueError("Travel time must be between 1 and 240 minutes, or blank.")
        instructions(rule.get("prep", []))
    instructions(value.get("bedtime", []))
    return value


def eligible_tasks(state, day):
    return [
        row
        for row in state["items"]
        if row["kind"] == "tasks"
        and not checklists.is_done(row, day.isoformat())
        and row.get("skipped_on") != day.isoformat()
        and (not row.get("due") or row["due"] <= day.isoformat())
    ]


def choose_focus(ids, day=None):
    day = day or date.fromisoformat(checklists.today())
    with checklists.transaction() as state:
        available = {row["id"] for row in eligible_tasks(state, day)}
        if (
            len(ids) > 3
            or len(set(ids)) != len(ids)
            or any(key not in available for key in ids)
        ):
            raise ValueError("Choose up to three pending tasks due on that day.")
        config = state.setdefault("assistant", defaults())
        previous = config.get("focus", {})
        if previous.get("day") != day.isoformat():
            config["other_focus"] = previous
        config["focus"] = {"day": day.isoformat(), "ids": ids}
        validate(config)


def save_preparation(title="", travel_minutes=None, prep=(), bedtime=None, remove=""):
    with checklists.transaction() as state:
        config = state.setdefault("assistant", defaults())
        if remove:
            config["appointments"] = [
                rule
                for rule in config.get("appointments", [])
                if rule["title"].casefold() != remove.casefold()
            ]
        else:
            if bedtime is not None:
                config["bedtime"] = list(bedtime)
            if title.strip():
                name = text(title)
                rule = dict(title=name, travel_minutes=travel_minutes, prep=list(prep))
                config["appointments"] = [
                    row
                    for row in config.get("appointments", [])
                    if row["title"].casefold() != name.casefold()
                ] + [rule]
            elif travel_minutes is not None or prep:
                raise ValueError(
                    "Enter the exact calendar title for appointment preparation."
                )
        validate(config)


def event_start(event):
    """Preserve calendar timezone/offset; all-day events have no leave-by time."""
    if event.get("all_day") or str(event.get("time", "")).upper() == "ALL DAY":
        return None
    value = event.get("start_dt")
    try:
        stamp = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value)
            if value
            else None
        )
        if stamp is None:
            stamp = datetime.combine(
                date.fromisoformat(str(event["date"])),
                time.fromisoformat(str(event["time"])[:5]),
            )
        return (stamp.replace(tzinfo=UK) if stamp.tzinfo is None else stamp).astimezone(
            UK
        )
    except (ValueError, TypeError, KeyError):
        return None


def focus_for(config, day):
    return next(
        (
            config[key]
            for key in ("focus", "other_focus")
            if config.get(key, {}).get("day") == day
        ),
        {},
    )


def briefing(state, events=(), now=None):
    now = (now or datetime.now(UK)).astimezone(UK)
    day = now.date()
    config = state.get("assistant", defaults())
    validate(config)
    available = {row["id"]: row for row in eligible_tasks(state, day)}
    focus = focus_for(config, day.isoformat())
    chosen = (
        [available[key] for key in focus.get("ids", []) if key in available]
        if focus.get("day") == day.isoformat()
        else []
    )
    timed = (
        [
            (event_start(event), index, event)
            for index, event in enumerate(events)
            if isinstance(event, dict)
        ]
        if isinstance(events, (list, tuple))
        else []
    )
    timed = sorted(
        (row for row in timed if row[0] is not None),
        key=lambda row: (row[0].astimezone(timezone.utc), row[1]),
    )
    future = [
        row
        for row in timed
        if row[0].date() == day
        and row[0].astimezone(timezone.utc) >= now.astimezone(timezone.utc)
    ]
    rules = {row["title"].casefold(): row for row in config.get("appointments", [])}
    appointment = None
    if future:
        start, index, event = future[0]
        rule = rules.get(str(event.get("title", "")).strip().casefold(), {})
        lines = [start.strftime("%H:%M") + " " + str(event.get("title", "Appointment"))]
        if event.get("location"):
            lines.append("Location: " + str(event["location"]))
        minutes = rule.get("travel_minutes")
        if minutes is not None:
            leave = (
                start.astimezone(timezone.utc) - timedelta(minutes=minutes)
            ).astimezone(UK)
            lines.append("Leave by: " + leave.strftime("%a %d %b %H:%M %Z"))
            lines.append(f"Using your {minutes}-minute travel time.")
            if leave.astimezone(timezone.utc) < now.astimezone(timezone.utc):
                lines.append("Planned leave time has passed.")
        lines.extend("[ ] " + line for line in rule.get("prep", []))
        appointment = dict(index=index, lines=lines)
    bedtime = []
    early = [
        row
        for row in timed
        if row[0].date() == day + timedelta(days=1) and row[0].hour < 12
    ]
    for start, _, event in early[:3]:
        bedtime.append(
            "Tomorrow "
            + start.strftime("%H:%M")
            + ": "
            + str(event.get("title", "Appointment"))
        )
        rule = rules.get(str(event.get("title", "")).strip().casefold(), {})
        bedtime.extend("[ ] " + line for line in rule.get("prep", []))
    if len(early) > 3:
        bedtime.append(f"{len(early) - 3} more early appointments; check calendar.")
    bedtime.extend("[ ] " + line for line in config.get("bedtime", []))
    bedtime = list(dict.fromkeys(bedtime))
    return dict(focus=chosen, appointment=appointment, bedtime=bedtime)


def print_section(printer, title, lines, *, line, left, wrap, safe):
    if not lines:
        return
    line(printer, "=")
    left(printer, title)
    line(printer, "-")
    for value in lines:
        wrap(printer, safe(value), width=40)
