"""Local day travel settings and a deterministic, car-aware itinerary planner."""

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import math
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from storage import PrivateStore

UK = ZoneInfo("Europe/London")
FILE = Path(__file__).resolve().parents[1] / "data" / "day_travel.json"
MODES = {"auto", "driving", "walking", "cycling", "transit"}


def key(address):
    return hashlib.sha256(" ".join(address.casefold().split()).encode()).hexdigest()


def text(value, maximum=500):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Use a short, single-line location or label.")
    return value.strip()


def integer(value, low, high):
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise ValueError("Use whole minutes within the displayed limits.") from None
    if not low <= n <= high:
        raise ValueError("Minutes are outside the supported range.")
    return n


def point(value):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(n) not in (int, float) or not math.isfinite(n) for n in value)
    ):
        raise ValueError("Enter valid latitude and longitude.")
    if not -90 <= value[0] <= 90 or not -180 <= value[1] <= 180:
        raise ValueError("Coordinates are outside the map.")
    return value


def defaults():
    return dict(
        version=1,
        home="",
        mode="auto",
        walk_minutes=25,
        car=True,
        buffer=10,
        home_minutes=30,
        parking=5,
        places={},
        days={},
        manual={},
    )


def validate(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Invalid travel settings.")
    text(value["home"])
    if value["mode"] not in MODES or type(value["car"]) is not bool:
        raise ValueError("Invalid travel mode.")
    for field, high in [("buffer", 120), ("home_minutes", 480), ("parking", 60)]:
        integer(value[field], 0, high)
    integer(value.get("walk_minutes", 25), 0, 120)
    for name, maximum in [("places", 200), ("days", 31), ("manual", 500)]:
        if not isinstance(value[name], dict) or len(value[name]) > maximum:
            raise ValueError("Too much saved travel data.")
    for identifier, place in value["places"].items():
        if identifier != key(text(place["address"])):
            raise ValueError("Invalid saved place.")
        if place.get("point") is not None:
            point(place["point"])
        if type(place.get("confirmed", False)) is not bool:
            raise ValueError("Invalid confirmation.")
        if (
            not isinstance(place.get("choices", []), list)
            or len(place.get("choices", [])) > 3
        ):
            raise ValueError("Invalid place choices.")
        for choice in place.get("choices", []):
            point(choice["point"])
            text(choice["label"])
    for day, row in value["days"].items():
        date.fromisoformat(day)
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("events"), list)
            or len(row["events"]) > 30
        ):
            raise ValueError("At most 30 events per day are supported.")
        if (
            not isinstance(row.get("overrides", {}), dict)
            or len(row.get("overrides", {})) > 30
        ):
            raise ValueError("Invalid event choices.")
        for event in row["events"]:
            if not re.fullmatch(r"[a-f0-9]{64}", event["id"]):
                raise ValueError("Invalid event identity.")
            text(event["title"], 200)
            text(event["address"])
            for field in ("start", "end"):
                if event[field] is not None and when(event[field]) is None:
                    raise ValueError("Invalid event time.")
        for identity, choice in row.get("overrides", {}).items():
            if not re.fullmatch(r"[a-f0-9]{64}", identity) or not isinstance(
                choice, dict
            ):
                raise ValueError("Invalid event choice.")
            if (
                choice.get("mode") not in MODES
                or choice.get("via") not in {"auto", "home", "direct"}
                or type(choice.get("skip")) is not bool
            ):
                raise ValueError("Invalid event choice.")
            if choice.get("end"):
                time.fromisoformat(choice["end"])
    for identity, minutes in value["manual"].items():
        if not re.fullmatch(
            r"[a-f0-9]{64}\|[a-f0-9]{64}\|(driving|walking|cycling|transit)", identity
        ):
            raise ValueError("Invalid journey override.")
        integer(minutes, 0, 1440)


def store():
    return PrivateStore(FILE, default=defaults, validate=validate, max_bytes=2_000_000)


def when(raw):
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return None
    return dt.replace(tzinfo=UK) if dt.tzinfo is None else dt.astimezone(UK)


def event_rows(events, day):
    result = []
    for event in events:
        start, end = when(event.get("start_dt")), when(event.get("end_dt"))
        if not start and str(event.get("date")) != day:
            continue
        if start and (
            start.date().isoformat() > day or (end or start).date().isoformat() < day
        ):
            continue
        identity = hashlib.sha256(
            "|".join(
                str(event.get(k, "")) for k in ("uid", "start_dt", "title")
            ).encode()
        ).hexdigest()
        result.append(
            dict(
                id=identity,
                title=text(
                    " ".join(str(event.get("title", "Untitled event")).split())[:200],
                    200,
                ),
                address=text(" ".join(str(event.get("location", "")).split())[:500]),
                start=start.isoformat() if start else None,
                end=end.isoformat()
                if end and start and end.timestamp() > start.timestamp()
                else None,
                all_day=bool(event.get("all_day")),
            )
        )
    if len(result) > 30:
        raise ValueError(
            "This day has more than 30 events; select the events to travel to in your calendar."
        )
    return sorted(
        result,
        key=lambda e: (
            when(e["start"]).timestamp() if e["start"] else float("inf"),
            e["title"],
        ),
    )


def place(address, state, label=None):
    saved = state["places"].get(key(address), {})
    return dict(
        id=key(address),
        address=address,
        label=label or address or "Location missing",
        point=saved.get("point") if saved.get("confirmed") else None,
        accuracy=saved.get("accuracy", ""),
    )


def same(a, b):
    if a["id"] == b["id"]:
        return True
    if not a.get("point") or not b.get("point"):
        return False
    lat1, lon1 = a["point"]
    lat2, lon2 = b["point"]
    return (
        math.hypot(
            (lat1 - lat2) * 111000,
            (lon1 - lon2) * 111000 * math.cos(math.radians(lat1)),
        )
        < 30
    )


def route_key(a, b, mode):
    return "|".join((a["id"], b["id"], mode))


def build(state, day, route, progress=lambda message: None, *, transit=None):
    """route(a,b,mode) returns minutes/geometry/source or None. Never infer transit schedules."""
    saved = state["days"].get(day, dict(events=[], overrides={}))
    warnings = list(saved.get("warnings", []))
    legs = []
    visits = []
    home = place(state["home"], state, "Home")
    car = dict(home) if state["car"] else None
    current = home
    previous_end = None
    previous = None
    events = []
    for original in saved["events"]:
        e = dict(original)
        override = saved.get("overrides", {}).get(e["id"], {})
        if override.get("skip"):
            continue
        e["choice"] = override
        e["start"] = when(e["start"])
        e["end"] = when(e["end"])
        if override.get("end") and e["start"]:
            finish = datetime.combine(
                e["start"].date(), time.fromisoformat(override["end"]), UK
            ).replace(fold=e["start"].fold)
            e["end"] = finish if finish > e["start"] else finish + timedelta(days=1)
        if e["all_day"] or not e["start"]:
            warnings.append(
                f"{e['title']}: all-day or untimed event; set a timed calendar entry to include it in the journey order."
            )
            continue
        if not e["end"]:
            warnings.append(
                e["title"]
                + ": finish time unknown; later journey feasibility is unverified."
            )
        if e["start"].date().isoformat() < day:
            warnings.append(
                e["title"]
                + ": already in progress at the start of this day; the initial home departure is only a calendar-based assumption."
            )
        e["start"] = e["start"].astimezone(timezone.utc)
        e["end"] = e["end"].astimezone(timezone.utc) if e["end"] else None
        events.append(e)
    points = {home["id"]: home} if state["home"] else {}
    for e in saved["events"]:
        if e["address"] and not saved.get("overrides", {}).get(e["id"], {}).get("skip"):
            p = place(e["address"], state, e["title"])
            points[p["id"]] = p
    for p in points.values():
        if p.get("accuracy") and "Approximate" in p["accuracy"]:
            warnings.append(p["label"] + ": " + p["accuracy"])
    memo = {}

    def piece(a, b, mode):
        if not a["address"] or not b["address"]:
            return None
        if same(a, b):
            return dict(minutes=0, geometry=[], source="Same location")
        identity = route_key(a, b, mode)
        if identity not in memo:
            if identity in state["manual"]:
                memo[identity] = dict(
                    minutes=state["manual"][identity],
                    geometry=[],
                    source="Your duration estimate",
                )
            elif not a.get("point") or not b.get("point") or mode == "transit":
                memo[identity] = None
            else:
                progress("Checking " + mode + " travel times")
                memo[identity] = route(a, b, mode)
        return memo[identity]

    def street_journey(a, b, requested, parked):
        mode = state["mode"] if requested == "auto" else requested
        steps = []
        next_car = parked
        if mode == "driving":
            if parked is None:
                mode = "walking"
                note = "No car available; walking suggested instead."
            elif not same(a, parked):
                steps.append((a, parked, "walking"))
                note = "Walk to collect your parked car, then drive."
            else:
                note = ""
            if mode == "driving":
                next_car = b
        else:
            note = ""
        steps.append((parked if steps else a, b, mode))
        parts = []
        duration = 0
        known = True
        for origin, dest, m in steps:
            info = piece(origin, dest, m)
            mins = math.ceil(info["minutes"]) if info else None
            if mins is None:
                known = False
            elif m == "driving" and not same(origin, dest):
                mins += state["parking"]
            if mins is not None:
                duration += mins
            parts.append(
                dict(
                    origin=origin,
                    destination=dest,
                    mode=m,
                    minutes=mins,
                    geometry=info.get("geometry", []) if info else [],
                    source=info.get("source", "") if info else "Duration needed",
                )
            )
        return dict(
            parts=parts, minutes=duration if known else None, note=note, car=next_car
        )

    def timed(trip, arrive_by=None, depart_after=None):
        total = trip["minutes"]
        depart = arrive = None
        if total is not None:
            depart = (
                (arrive_by - timedelta(minutes=total)) if arrive_by else depart_after
            )
            if depart_after and depart and depart < depart_after:
                depart = depart_after
            arrive = depart + timedelta(minutes=total) if depart else None
        trip.update(departure=depart, arrival=arrive)
        return trip

    def public(a, b, parked, arrive_by, depart_after):
        identity = route_key(a, b, "transit")
        if identity in state["manual"]:
            return timed(
                street_journey(a, b, "transit", parked), arrive_by, depart_after
            )
        info = None
        if transit and a.get("point") and b.get("point"):
            progress("Checking bus and train journeys for the event time")
            cache_id = (identity, str(arrive_by), str(depart_after))
            if cache_id not in memo:
                memo[cache_id] = transit(
                    a, b, arrive_by=arrive_by, depart_after=depart_after
                )
            info = memo[cache_id]
        if not info:
            return timed(
                street_journey(a, b, "transit", parked), arrive_by, depart_after
            )
        depart = when(info.get("departure"))
        arrive = when(info.get("arrival"))
        depart = depart.astimezone(timezone.utc) if depart else None
        arrive = arrive.astimezone(timezone.utc) if arrive else None
        if (
            not depart
            or not arrive
            or arrive < depart
            or (depart_after and depart < depart_after)
            or (arrive_by and arrive > arrive_by)
        ):
            return timed(
                street_journey(a, b, "transit", parked), arrive_by, depart_after
            )
        part = dict(
            origin=a,
            destination=b,
            mode="transit",
            minutes=info["minutes"],
            geometry=info.get("geometry", []),
            source=info.get("source", "Scheduled public transport"),
            steps=info.get("steps", []),
            acknowledgements=info.get("acknowledgements", ""),
        )
        return dict(
            parts=[part],
            minutes=info["minutes"],
            note="Includes the provider’s walking, waiting and changes; check disruption updates.",
            car=parked,
            departure=depart,
            arrival=arrive,
        )

    def journey(a, b, requested, parked, arrive_by=None, depart_after=None):
        chosen = (
            (state["mode"] if "walk_minutes" in state else "auto")
            if requested == "auto"
            else requested
        )
        if chosen == "transit":
            return public(a, b, parked, arrive_by, depart_after)
        if chosen != "auto":
            return timed(street_journey(a, b, chosen, parked), arrive_by, depart_after)
        walking = timed(
            street_journey(a, b, "walking", parked), arrive_by, depart_after
        )

        def fits(trip):
            return trip["minutes"] is not None and (
                not arrive_by or trip["arrival"] and trip["arrival"] <= arrive_by
            )

        if (
            walking["minutes"] is not None
            and walking["minutes"] <= state.get("walk_minutes", 25)
            and fits(walking)
        ):
            walking["note"] = (
                "Walking preferred: within your short-walk limit and fits the available time."
            )
            return walking
        bus = public(a, b, parked, arrive_by, depart_after)
        if fits(bus):
            return bus
        if parked:
            driving = timed(
                street_journey(a, b, "driving", parked), arrive_by, depart_after
            )
            if driving["minutes"] is not None:
                driving["note"] = (
                    driving["note"] + " " if driving["note"] else ""
                ) + "No usable public transport journey returned; driving fallback."
                return driving
        if walking["minutes"] is not None:
            walking["note"] = (
                "No usable public transport journey returned. Walking fallback exceeds the preferred limit or available time; review it."
            )
            return walking
        return bus

    def append(trip, arrival=None, depart=None):
        departure = trip.get("departure")
        for part in trip["parts"]:
            item = dict(
                part,
                depart=departure.isoformat() if departure else None,
                arrive=None,
                note=trip["note"],
            )
            if departure and part["minutes"] is not None:
                departure = departure + timedelta(minutes=part["minutes"])
                item["arrive"] = departure.isoformat()
                if (
                    part["mode"] == "transit"
                    and len(trip["parts"]) == 1
                    and trip.get("arrival")
                ):
                    item["arrive"] = trip["arrival"].isoformat()
            legs.append(item)

    for e in events:
        dest = place(e["address"], state, e["title"])
        if not e["address"]:
            warnings.append(
                e["title"] + ": no location; travel feasibility is unknown."
            )
        arrival = e["start"] - timedelta(minutes=state["buffer"])
        mode = e["choice"].get("mode", "auto")
        direct = journey(current, dest, mode, car, arrival, previous_end)
        message = (
            "Start from home."
            if previous is None
            else "Travel directly to the next event."
        )
        used_home = False
        if (
            previous is not None
            and not same(current, home)
            and not same(dest, home)
            and e["choice"].get("via") != "direct"
        ):
            back = journey(current, home, "auto", car, depart_after=previous_end)
            outbound = journey(
                home, dest, mode, back["car"], arrival, back.get("arrival")
            )
            known = (
                previous_end
                and back.get("arrival") is not None
                and outbound.get("departure") is not None
                and outbound.get("arrival") is not None
                and outbound["arrival"] <= arrival
            )
            home_time = (
                math.floor(
                    (outbound["departure"] - back["arrival"]).total_seconds() / 60
                )
                if known
                else None
            )
            preference = e["choice"].get("via", "auto")
            if known and home_time >= state["home_minutes"] and preference != "direct":
                append(back, None, previous_end)
                append(outbound, arrival)
                car = outbound["car"]
                used_home = True
                message = (
                    f"Return home between events: about {home_time} minutes at home."
                )
            elif preference == "home":
                message = "Requested return home does not fit, or its travel time is unknown. Go direct and review the timings."
                warnings.append(
                    e["title"] + ": requested home stop could not be verified."
                )
            elif home_time is None:
                message = "Home stop cannot be assessed: add the previous end time and all journey durations."
            else:
                message = f"Go direct: a return home leaves {max(0, home_time)} minutes at home; your minimum is {state['home_minutes']}."
        if not used_home:
            append(direct)
            car = direct["car"]
            if (
                previous_end
                and direct["minutes"] is not None
                and direct.get("arrival") is not None
                and direct["arrival"] > arrival
            ):
                late = math.ceil((direct["arrival"] - arrival).total_seconds() / 60)
                warnings.append(
                    f"{e['title']}: journey exceeds the available gap by {late} minutes, including your arrival buffer."
                )
            if previous_end and previous_end > e["start"]:
                warnings.append(e["title"] + ": calendar events overlap.")
        if direct["minutes"] is None and not used_home:
            warnings.append(
                e["title"]
                + ": travel time is unknown; do not rely on the suggested departure time."
            )
        visits.append(
            dict(
                id=e["id"],
                title=e["title"],
                start=e["start"].isoformat(),
                end=e["end"].isoformat() if e["end"] else None,
                location=dest,
                message=message,
                car_at=car["label"] if car else "No car available",
            )
        )
        current = dest
        previous_end = e["end"]
        previous = e
    if previous is not None:
        back = journey(current, home, "auto", car, depart_after=previous_end)
        append(back, None, previous_end)
        if not previous_end:
            warnings.append(
                "Final event has no known end time; return-home departure is not scheduled."
            )
        if back["minutes"] is None:
            warnings.append("Return-home duration is unknown.")
        car = back["car"]
    if car and not same(car, home):
        warnings.append(
            "Your car finishes parked at "
            + car["label"]
            + ". Collect it separately or change your travel mode."
        )
    return dict(
        day=day,
        legs=legs,
        visits=visits,
        points=list(points.values()),
        warnings=list(dict.fromkeys(warnings)),
        car_at=car["label"] if car else "No car available",
    )
