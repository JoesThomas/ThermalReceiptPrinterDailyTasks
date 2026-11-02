"""Readable English directions from OSRM's structured maneuvers; no invented routes."""

import math


def clean(value, limit=160):
    return " ".join(str(value or "").split())[:limit]


def distance(raw):
    if (
        type(raw) not in (int, float)
        or not 0 <= raw <= 10_000_000
        or not math.isfinite(raw)
    ):
        return ""
    return f"{raw / 1000:.1f} km" if raw >= 1000 else f"{math.ceil(raw)} m"


def instruction(step):
    maneuver = step.get("maneuver") or {}
    kind = clean(maneuver.get("type"), 40)
    modifier = clean(maneuver.get("modifier"), 30)
    direction = {
        "left": "left",
        "right": "right",
        "slight left": "slightly left",
        "slight right": "slightly right",
        "sharp left": "sharply left",
        "sharp right": "sharply right",
        "straight": "straight ahead",
        "uturn": "around",
    }.get(modifier, "")
    name = clean(step.get("name") or step.get("ref"))
    road = (" onto " + name) if name else ""
    if kind == "depart":
        bearing = maneuver.get("bearing_after")
        compass = (
            [
                "north",
                "northeast",
                "east",
                "southeast",
                "south",
                "southwest",
                "west",
                "northwest",
            ][int((bearing + 22.5) // 45) % 8]
            if type(bearing) in (int, float)
            and 0 <= bearing <= 360
            and math.isfinite(bearing)
            else ""
        )
        return (
            "Start"
            + (" heading " + compass if compass else "")
            + (" on " + name if name else "")
        )
    if kind == "arrive":
        return "Arrive at your destination" + (
            " on the " + modifier if modifier in {"left", "right"} else ""
        )
    if kind in {
        "roundabout",
        "rotary",
        "roundabout turn",
        "exit roundabout",
        "exit rotary",
    }:
        exit_number = maneuver.get("exit")
        exit_text = (
            f" and take exit {exit_number}"
            if type(exit_number) is int and 0 < exit_number <= 30
            else ""
        )
        return (
            "Leave the roundabout"
            if kind.startswith("exit")
            else "At the roundabout" + exit_text
        ) + road
    if kind == "fork":
        return "At the fork, keep " + (direction or "following the route") + road
    if kind == "merge":
        return "Merge" + (" " + direction if direction else "") + road
    if kind in {"on ramp", "off ramp"}:
        return (
            ("Take the exit" if kind == "off ramp" else "Take the ramp")
            + (" " + direction if direction else "")
            + road
        )
    if kind == "turn" and modifier == "uturn":
        return "Make a U-turn" + road
    if kind in {"turn", "end of road"}:
        return (
            ("At the end of the road, turn " if kind == "end of road" else "Turn ")
            + (direction or "as shown on the route")
            + road
        )
    if clean(step.get("mode"), 30) == "ferry":
        return "Take the ferry" + (" " + name if name else "")
    return (
        "Continue"
        + (" " + direction if direction else "")
        + (" on " + name if name else "")
    )


def build(route):
    directions = []
    truncated = False
    legs = route.get("legs") or []
    if not isinstance(legs, list):
        return [], False
    for leg in legs[:10]:
        steps = leg.get("steps") if isinstance(leg, dict) else None
        if not isinstance(steps, list):
            continue
        for step in steps:
            if len(directions) >= 200:
                truncated = True
                break
            if not isinstance(step, dict) or not isinstance(step.get("maneuver"), dict):
                continue
            directions.append(
                dict(
                    instruction=instruction(step),
                    distance=distance(step.get("distance")),
                )
            )
    if len(legs) > 10:
        truncated = True
    return directions, truncated
