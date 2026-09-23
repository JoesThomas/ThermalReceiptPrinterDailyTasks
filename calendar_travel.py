from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo
import re
import requests

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
UK_TZ = ZoneInfo("Europe/London")


@dataclass
class TravelOption:
    mode: str
    duration_minutes: int
    leave_by: datetime
    arrive_by: datetime
    summary: str
    distance_m: int | None = None
    detail: list[str] = field(default_factory=list)


def _duration_seconds(value: str) -> int:
    # Google duration strings are normally e.g. "1234s".
    m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(value or ""))
    return int(float(m.group(1))) if m else 0


def _utc_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UK_TZ)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _waypoint(address: str) -> dict:
    return {"address": address}


def _compute_route(api_key: str, body: dict, field_mask: str) -> dict | None:
    if not api_key:
        return None
    response = requests.post(
        ROUTES_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
        },
        json=body,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    routes = data.get("routes") or []
    return routes[0] if routes else None


def _drive_route(api_key: str, origin: str, destination: str,
                 event_start: datetime, buffer_minutes: int) -> TravelOption | None:
    # Estimate a departure from a first-pass non-traffic duration, then request
    # traffic-aware routing for that expected departure time.
    first = _compute_route(
        api_key,
        {
            "origin": _waypoint(origin),
            "destination": _waypoint(destination),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_UNAWARE",
            "languageCode": "en-GB",
            "units": "METRIC",
        },
        "routes.duration,routes.distanceMeters",
    )
    if not first:
        return None

    first_minutes = max(1, round(_duration_seconds(first.get("duration")) / 60))
    estimated_departure = event_start - timedelta(
        minutes=first_minutes + buffer_minutes
    )

    body = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "languageCode": "en-GB",
        "units": "METRIC",
    }
    if estimated_departure > datetime.now(event_start.tzinfo):
        body["departureTime"] = _utc_rfc3339(estimated_departure)

    route = _compute_route(
        api_key,
        body,
        "routes.duration,routes.distanceMeters",
    ) or first

    minutes = max(1, round(_duration_seconds(route.get("duration")) / 60))
    leave = event_start - timedelta(minutes=minutes + buffer_minutes)
    return TravelOption(
        mode="DRIVE",
        duration_minutes=minutes,
        leave_by=leave,
        arrive_by=event_start - timedelta(minutes=buffer_minutes),
        summary="DRIVE",
        distance_m=route.get("distanceMeters"),
    )


def _walk_route(api_key: str, origin: str, destination: str,
                event_start: datetime, buffer_minutes: int) -> TravelOption | None:
    route = _compute_route(
        api_key,
        {
            "origin": _waypoint(origin),
            "destination": _waypoint(destination),
            "travelMode": "WALK",
            "languageCode": "en-GB",
            "units": "METRIC",
        },
        "routes.duration,routes.distanceMeters",
    )
    if not route:
        return None
    minutes = max(1, round(_duration_seconds(route.get("duration")) / 60))
    leave = event_start - timedelta(minutes=minutes + buffer_minutes)
    return TravelOption(
        mode="WALK",
        duration_minutes=minutes,
        leave_by=leave,
        arrive_by=event_start - timedelta(minutes=buffer_minutes),
        summary="WALK",
        distance_m=route.get("distanceMeters"),
    )


def _transit_step_label(step: dict) -> str | None:
    mode = str(step.get("travelMode", "")).upper()
    if mode == "WALK":
        seconds = _duration_seconds(step.get("staticDuration") or step.get("duration"))
        mins = max(1, round(seconds / 60)) if seconds else None
        return f"WALK {mins} MIN" if mins else "WALK"

    if mode != "TRANSIT":
        return None

    td = step.get("transitDetails") or {}
    line = td.get("transitLine") or {}
    vehicle = (line.get("vehicle") or {}).get("type", "")
    short = line.get("nameShort") or line.get("name") or ""
    vehicle_names = {
        "BUS": "BUS",
        "INTERCITY_BUS": "BUS",
        "TROLLEYBUS": "BUS",
        "TRAM": "TRAM",
        "SUBWAY": "METRO",
        "METRO_RAIL": "METRO",
        "HEAVY_RAIL": "TRAIN",
        "COMMUTER_TRAIN": "TRAIN",
        "LONG_DISTANCE_TRAIN": "TRAIN",
        "HIGH_SPEED_TRAIN": "TRAIN",
        "RAIL": "TRAIN",
        "FERRY": "FERRY",
    }
    kind = vehicle_names.get(str(vehicle).upper(), "TRANSIT")
    return f"{kind} {short}".strip()


def _transit_route(api_key: str, origin: str, destination: str,
                   event_start: datetime, buffer_minutes: int) -> TravelOption | None:
    # For transit, arrivalTime is supported, so ask for a journey that gets the
    # user there before the event buffer rather than calculating from "now".
    target_arrival = event_start - timedelta(minutes=buffer_minutes)
    route = _compute_route(
        api_key,
        {
            "origin": _waypoint(origin),
            "destination": _waypoint(destination),
            "travelMode": "TRANSIT",
            "arrivalTime": _utc_rfc3339(target_arrival),
            "languageCode": "en-GB",
            "units": "METRIC",
            "transitPreferences": {
                "routingPreference": "FEWER_TRANSFERS"
            },
        },
        (
            "routes.duration,routes.distanceMeters,"
            "routes.legs.steps.travelMode,"
            "routes.legs.steps.staticDuration,"
            "routes.legs.steps.transitDetails"
        ),
    )
    if not route:
        return None

    minutes = max(1, round(_duration_seconds(route.get("duration")) / 60))
    labels = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            label = _transit_step_label(step)
            if label and (not labels or labels[-1] != label):
                labels.append(label)

    compact = []
    for label in labels:
        if label.startswith("WALK "):
            compact.append("WALK")
        else:
            compact.append(label)
    summary = " + ".join(compact) if compact else "PUBLIC TRANSPORT"

    leave = target_arrival - timedelta(minutes=minutes)
    return TravelOption(
        mode="TRANSIT",
        duration_minutes=minutes,
        leave_by=leave,
        arrive_by=target_arrival,
        summary=summary,
        distance_m=route.get("distanceMeters"),
        detail=labels,
    )


def travel_options(
    *,
    api_key: str,
    origin: str,
    destination: str,
    event_start: datetime,
    drive_buffer_minutes: int = 10,
    transit_buffer_minutes: int = 15,
    walk_buffer_minutes: int = 10,
    show_walk_under_minutes: int = 25,
) -> list[TravelOption]:
    if not api_key or not origin or not destination:
        return []

    options: list[TravelOption] = []

    try:
        drive = _drive_route(
            api_key, origin, destination, event_start, drive_buffer_minutes
        )
        if drive:
            options.append(drive)
    except requests.RequestException:
        pass

    try:
        transit = _transit_route(
            api_key, origin, destination, event_start, transit_buffer_minutes
        )
        if transit:
            options.append(transit)
    except requests.RequestException:
        pass

    try:
        walk = _walk_route(
            api_key, origin, destination, event_start, walk_buffer_minutes
        )
        if walk and walk.duration_minutes <= show_walk_under_minutes:
            options.append(walk)
    except requests.RequestException:
        pass

    # Display options without declaring a "winner".
    order = {"WALK": 0, "DRIVE": 1, "TRANSIT": 2}
    options.sort(key=lambda x: order.get(x.mode, 99))
    return options


def sensible_chained_origin(
    *,
    home: str,
    previous_event: dict | None,
    current_event: dict,
    minimum_gap_minutes: int = 0,
) -> tuple[str, str]:
    """
    Use the previous physical event as the next origin when it finishes before
    the next event starts. Otherwise fall back to home.
    """
    if not previous_event:
        return home, "HOME"

    prev_location = (previous_event.get("location") or "").strip()
    prev_end = previous_event.get("end_dt")
    current_start = current_event.get("start_dt")

    if (
        prev_location
        and isinstance(prev_end, datetime)
        and isinstance(current_start, datetime)
        and prev_end + timedelta(minutes=minimum_gap_minutes) <= current_start
    ):
        return prev_location, previous_event.get("title", "PREVIOUS EVENT").upper()

    return home, "HOME"
