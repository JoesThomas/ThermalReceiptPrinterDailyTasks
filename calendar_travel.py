from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


_ROUTE_CACHE = {}


def clear_route_cache():
    """Clear cached route responses before a new receipt run."""
    _ROUTE_CACHE.clear()

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


@dataclass
class TransitLeg:
    departure_time: datetime | None
    arrival_time: datetime | None
    instruction: str
    mode: str = "TRANSIT"

    # Public-transport information.
    route_name: str = ""
    departure_stop: str = ""
    arrival_stop: str = ""
    headsign: str = ""


@dataclass
class TravelOption:
    mode: str
    duration_minutes: int
    leave_by: datetime
    arrive_by: datetime | None = None
    summary: str = ""
    distance_metres: int | None = None
    transit_legs: list[TransitLeg] = field(default_factory=list)
    earlier_options: list["TravelOption"] = field(default_factory=list)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except (TypeError, ValueError):
        return None


def _minutes(duration: str | None) -> int:
    if not duration or not duration.endswith("s"):
        return 0
    try:
        return max(1, round(float(duration[:-1]) / 60))
    except ValueError:
        return 0


def _request_route(api_key: str, origin: str, destination: str, mode: str,
                   *, arrival_time: datetime | None = None) -> dict[str, Any] | None:
    body: dict[str, Any] = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": mode,
        "languageCode": "en-GB",
        "units": "METRIC",
    }
    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    if mode == "TRANSIT" and arrival_time:
        body["arrivalTime"] = _rfc3339(arrival_time)

    fields = (
        "routes.duration,routes.legs.duration,routes.legs.steps.travelMode,"
        "routes.legs.steps.staticDuration,routes.legs.steps.navigationInstruction,"
        "routes.legs.steps.transitDetails,routes.description,"
        "routes.distanceMeters,routes.polyline.encodedPolyline"
    )
    response = requests.post(
        ROUTES_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": fields,
        },
        json=body,
        timeout=20,
    )
    response.raise_for_status()
    routes = response.json().get("routes") or []
    return routes[0] if routes else None



def _place_name(value: Any) -> str:
    """Return a readable name from either a string or localized-text object."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            return name
        if isinstance(name, dict):
            return str(name.get("text") or "")
        return str(value.get("text") or "")
    return ""

def _transit_option(route: dict[str, Any], target_arrival: datetime) -> TravelOption | None:
    duration = _minutes(route.get("duration"))
    if not duration:
        return None

    legs_out: list[TransitLeg] = []
    first_departure = None
    last_arrival = None
    labels: list[str] = []

    for leg in route.get("legs") or []:
        for step in leg.get("steps") or []:
            mode = (step.get("travelMode") or "").upper()
            nav = step.get("navigationInstruction") or {}
            instruction_text = nav.get("instructions") or ""

            if mode == "TRANSIT":
                td = step.get("transitDetails") or {}
                stop = td.get("stopDetails") or {}
                line = td.get("transitLine") or {}
                vehicle = line.get("vehicle") or {}
                dep = _parse_time(stop.get("departureTime"))
                arr = _parse_time(stop.get("arrivalTime"))
                first_departure = first_departure or dep
                last_arrival = arr or last_arrival

                vehicle_name = _place_name(vehicle.get("name")) or vehicle.get("type") or "TRANSIT"
                short = line.get("nameShort") or line.get("name") or ""
                headsign = td.get("headsign") or ""
                dep_stop = _place_name(stop.get("departureStop"))
                arr_stop = _place_name(stop.get("arrivalStop"))

                label = " ".join(x for x in (vehicle_name.upper(), str(short)) if x).strip()
                if label and label not in labels:
                    labels.append(label)
                instruction = label or "TRANSIT"
                if dep_stop and arr_stop:
                    instruction += f" {dep_stop} -> {arr_stop}"
                elif headsign:
                    instruction += f" -> {headsign}"
                legs_out.append(
                    TransitLeg(
                        departure_time=dep,
                        arrival_time=arr,
                        instruction=instruction.strip(),
                        mode=vehicle_name.upper(),
                        route_name=str(short).strip(),
                        departure_stop=dep_stop,
                        arrival_stop=arr_stop,
                        headsign=str(headsign).strip(),
                    )
                )
            elif mode == "WALK":
                step_minutes = _minutes(step.get("staticDuration"))
                instruction = "WALK"
                if step_minutes:
                    instruction += f" {step_minutes} MIN"
                if instruction_text:
                    instruction += f" - {instruction_text}"
                legs_out.append(TransitLeg(None, None, instruction, "WALK"))

    arrive = last_arrival or target_arrival
    leave = first_departure or (arrive - timedelta(minutes=duration))

    # If the route starts with walking, the actual journey must begin before
    # the first vehicle departure. The route duration gives the safest overall
    # leave time for receipt purposes.
    route_leave = arrive - timedelta(minutes=duration)
    leave = min(leave, route_leave)

    return TravelOption(
        mode="TRANSIT",
        duration_minutes=duration,
        leave_by=leave,
        arrive_by=arrive,
        summary=" + ".join(labels) or "PUBLIC TRANSPORT",
        distance_metres=route.get("distanceMeters"),
        transit_legs=legs_out,
    )

def _journey_key(option: TravelOption) -> tuple:
    return tuple(
        (leg.departure_time.isoformat() if leg.departure_time else "", leg.instruction)
        for leg in option.transit_legs
    ) or (option.leave_by.replace(second=0, microsecond=0).isoformat(), option.summary)


def _transit_with_earlier(api_key: str, origin: str, destination: str,
                          target_arrival: datetime, earlier_count: int = 3) -> TravelOption | None:
    route = _request_route(api_key, origin, destination, "TRANSIT", arrival_time=target_arrival)
    if not route:
        return None
    recommended = _transit_option(route, target_arrival)
    if not recommended:
        return None

    seen = {_journey_key(recommended)}
    earlier: list[TravelOption] = []
    # Work backwards far enough to find distinct complete journeys, rather than
    # assuming that every earlier target produces a different service.
    for offset in range(10, 121, 10):
        if len(earlier) >= earlier_count:
            break
        target = target_arrival - timedelta(minutes=offset)
        route = _request_route(api_key, origin, destination, "TRANSIT", arrival_time=target)
        if not route:
            continue
        option = _transit_option(route, target)
        if not option:
            continue
        key = _journey_key(option)
        if key in seen or option.leave_by >= recommended.leave_by:
            continue
        seen.add(key)
        earlier.append(option)

    # Closest earlier journey first.
    earlier.sort(key=lambda x: x.leave_by, reverse=True)
    recommended.earlier_options = earlier[:earlier_count]
    return recommended

def clean_calendar_location(location):
    """
    Clean common Google Calendar / email-generated
    location strings before sending them to Routes.
    """
    if not location:
        return ""

    location = str(location).strip()

    # Collapse whitespace.
    location = re.sub(
        r"\s+",
        " ",
        location,
    )

    lower = location.lower()

    # Known Birmingham stations.
    known_locations = {
        "birmingham new street":
            "Birmingham New Street Station, Birmingham, UK",

        "new street station":
            "Birmingham New Street Station, Birmingham, UK",

        "birmingham moor street":
            "Birmingham Moor Street Station, Birmingham, UK",

        "birmingham snow hill":
            "Birmingham Snow Hill Station, Birmingham, UK",

        "birmingham international":
            "Birmingham International Station, Birmingham, UK",
    }

    for phrase, canonical in known_locations.items():
        if phrase in lower:
            return canonical

    return location

def travel_options(api_key: str, origin: str, destination: str, event_start: datetime,
                   drive_buffer_minutes: int = 10, transit_buffer_minutes: int = 15,
                   walk_buffer_minutes: int = 10, show_walk_under_minutes: int = 25):
    options: list[TravelOption] = []

    try:
        drive = _request_route(api_key, origin, destination, "DRIVE")
        if drive:
            mins = _minutes(drive.get("duration"))
            if mins:
                options.append(TravelOption(
                    mode="DRIVE", duration_minutes=mins,
                    leave_by=event_start - timedelta(minutes=mins + drive_buffer_minutes),
                    arrive_by=event_start - timedelta(minutes=drive_buffer_minutes),
                    summary=drive.get("description") or "",
                    distance_metres=drive.get("distanceMeters"),
                ))
    except requests.RequestException:
        pass

    try:
        target = event_start - timedelta(minutes=transit_buffer_minutes)
        transit = _transit_with_earlier(api_key, origin, destination, target, earlier_count=3)
        if transit:
            options.append(transit)
    except requests.RequestException:
        pass

    try:
        walk = _request_route(api_key, origin, destination, "WALK")
        if walk:
            mins = _minutes(walk.get("duration"))
            if mins and mins <= show_walk_under_minutes:
                options.append(TravelOption(
                    mode="WALK", duration_minutes=mins,
                    leave_by=event_start - timedelta(minutes=mins + walk_buffer_minutes),
                    arrive_by=event_start - timedelta(minutes=walk_buffer_minutes),
                    summary=walk.get("description") or "",
                    distance_metres=walk.get("distanceMeters"),
                ))
    except requests.RequestException:
        pass

    return options


def sensible_chained_origin(home: str, previous_event: dict | None, current_event: dict):
    if previous_event:
        previous_location = (previous_event.get("location") or "").strip()
        previous_start = previous_event.get("start_dt")
        current_start = current_event.get("start_dt")
        if previous_location and previous_start and current_start:
            # Use the previous appointment as the origin when it occurs earlier
            # the same day; otherwise start from home.
            if previous_start.date() == current_start.date() and previous_start < current_start:
                return previous_location, "PREVIOUS EVENT"
    return home, "HOME"
