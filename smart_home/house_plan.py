"""Encrypted, owner-drawn room rectangles and sensor positions; no SVG uploads."""

import math
import re
import secrets

ID = re.compile(r"[a-f0-9]{32}")
SENSOR = re.compile(r"[a-f0-9]{64}")


def empty():
    return {"rooms": [], "positions": {}}


def label(value, limit=60):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid room or sensor label.")
    return value.strip()


def number(value):
    try:
        n = float(value)
    except (ValueError, TypeError):
        raise ValueError("Use numeric layout positions.") from None
    if not math.isfinite(n) or not 0 <= n <= 100:
        raise ValueError("Layout positions must be 0–100 percent.")
    return round(n, 2)


def validate(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"rooms", "positions"}
        or not isinstance(value["rooms"], list)
        or len(value["rooms"]) > 30
        or not isinstance(value["positions"], dict)
        or len(value["positions"]) > 100
    ):
        raise ValueError("Invalid house layout.")
    ids = set()
    floors = set()
    for room in value["rooms"]:
        if (
            not isinstance(room, dict)
            or set(room) != {"id", "name", "floor", "x", "y", "w", "h"}
            or not isinstance(room["id"], str)
            or not ID.fullmatch(room["id"])
            or room["id"] in ids
        ):
            raise ValueError("Invalid room identity.")
        ids.add(room["id"])
        label(room["name"])
        floors.add(label(room["floor"], 32))
        x, y, w, h = [number(room[k]) for k in ("x", "y", "w", "h")]
        if w < 5 or h < 5 or x + w > 100 or y + h > 100:
            raise ValueError("Rooms must fit inside the floor plan.")
    if len(floors) > 4:
        raise ValueError("Use no more than four floors.")
    for sensor, pos in value["positions"].items():
        if (
            not isinstance(sensor, str)
            or not SENSOR.fullmatch(sensor)
            or not isinstance(pos, dict)
            or set(pos) != {"room", "x", "y", "name"}
            or not isinstance(pos["room"], str)
            or pos["room"] not in ids
        ):
            raise ValueError("Invalid sensor position.")
        number(pos["x"])
        number(pos["y"])
        label(pos["name"], 80)


def save_room(layout, fields):
    identifier = fields.get("room_id") or secrets.token_hex(16)
    if fields.get("room_id") and not any(
        r["id"] == identifier for r in layout["rooms"]
    ):
        raise ValueError("Room no longer exists.")
    room = dict(
        id=identifier,
        name=label(fields.get("name", "")),
        floor=label(fields.get("floor", ""), 32),
        **{k: number(fields.get(k)) for k in ("x", "y", "w", "h")},
    )
    layout["rooms"] = [r for r in layout["rooms"] if r["id"] != identifier] + [room]
    validate(layout)
    return identifier


def save_sensor(layout, fields, sensors):
    identifier = fields.get("sensor_id", "")
    found = next((s for s in sensors if s["id"] == identifier), None)
    if not found:
        raise ValueError("Refresh Yale status and select a reported sensor.")
    layout["positions"][identifier] = dict(
        room=fields.get("room_id", ""),
        x=number(fields.get("x")),
        y=number(fields.get("y")),
        name=label(fields.get("name") or found["name"], 80),
    )
    validate(layout)


def render(layout, sensors):
    validate(layout)
    reports = {s["id"]: s for s in sensors}
    floors = []
    for floor in dict.fromkeys(r["floor"] for r in layout["rooms"]):
        rooms = [
            dict(
                r,
                sx=20 + r["x"] * 10,
                sy=20 + r["y"] * 6,
                sw=r["w"] * 10,
                sh=r["h"] * 6,
                label_x=28 + r["x"] * 10,
                label_y=43 + r["y"] * 6,
            )
            for r in layout["rooms"]
            if r["floor"] == floor
        ]
        markers = []
        for identifier, pos in layout["positions"].items():
            room = next((r for r in rooms if r["id"] == pos["room"]), None)
            if not room:
                continue
            report = reports.get(identifier, {})
            state = report.get("state", "unknown")
            if state not in {
                "triggered",
                "open",
                "closed",
                "motion",
                "tamper",
                "fault",
                "offline",
                "unknown",
            }:
                state = "unknown"
            markers.append(
                dict(
                    id=identifier,
                    name=pos["name"],
                    state=state,
                    label=report.get("label", "Trigger status unavailable"),
                    flags=report.get("flags", [])
                    if report
                    else ["No sensor report available"],
                    symbol={
                        "triggered": "!",
                        "open": "O",
                        "closed": "C",
                        "motion": "M",
                        "tamper": "T",
                        "fault": "F",
                        "offline": "X",
                        "unknown": "?",
                    }[state],
                    cx=room["sx"] + room["sw"] * pos["x"] / 100,
                    cy=room["sy"] + room["sh"] * pos["y"] / 100,
                )
            )
        floors.append(dict(name=floor, rooms=rooms, markers=markers))
    return dict(
        floors=floors,
        rooms=layout["rooms"],
        positions=layout["positions"],
        sensor_count=len(sensors),
        unmapped=[s for s in sensors if s["id"] not in layout["positions"]],
    )
