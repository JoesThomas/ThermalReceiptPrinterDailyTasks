"""Bounded scheduled public transport from TransportAPI's documented public_journey API."""

from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
from services import travel_routes
from services.day_travel import when, point

URL = "https://transportapi.com/v3/uk/public_journey.json"


def credentials(private=None):
    saved = private.get("transport_api", {}) if isinstance(private, dict) else {}
    if not isinstance(saved, dict):
        saved = {}
    values = (
        os.environ.get("RECEIPT_TRANSPORT_APP_ID") or saved.get("app_id", ""),
        os.environ.get("RECEIPT_TRANSPORT_APP_KEY") or saved.get("app_key", ""),
    )
    return tuple(
        v
        if isinstance(v, str)
        and 0 < len(v) <= 256
        and all(32 < ord(c) < 127 for c in v)
        else ""
        for v in values
    )


def timestamp(raw):
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def clean(raw, limit=200):
    return " ".join(str(raw or "").split())[:limit]


def parse(data, arrive_by=None, depart_after=None):
    if not isinstance(data, dict) or not isinstance(data.get("routes"), list):
        return None
    choices = []
    for route in data["routes"][:20]:
        if not isinstance(route, dict):
            continue
        depart = timestamp(route.get("departure_datetime"))
        arrive = timestamp(route.get("arrival_datetime"))
        if (
            not depart
            or not arrive
            or not 0 < (arrive - depart).total_seconds() <= 86400
        ):
            continue
        # Explicitly reject a route which would require leaving an earlier event early.
        if depart_after and depart < depart_after:
            continue
        if arrive_by and (
            arrive > arrive_by or arrive < arrive_by - timedelta(hours=24)
        ):
            continue
        if depart_after and depart > depart_after + timedelta(hours=24):
            continue
        steps = []
        geometry = []
        has_vehicle = False
        for part in (route.get("route_parts") or [])[:60]:
            if not isinstance(part, dict):
                continue
            mode = clean(part.get("mode"), 30)
            has_vehicle |= mode not in {"foot", "wait", "unknown", ""}
            steps.append(
                dict(
                    mode=mode,
                    line=clean(part.get("line_name"), 80),
                    origin=clean(part.get("from_point_name")),
                    destination=clean(part.get("to_point_name")),
                    headsign=clean(part.get("destination")),
                    depart=clean(part.get("departure_time"), 8),
                    arrive=clean(part.get("arrival_time"), 8),
                    depart_at=timestamp(part.get("departure_datetime")).isoformat()
                    if timestamp(part.get("departure_datetime"))
                    else None,
                    arrive_at=timestamp(part.get("arrival_datetime")).isoformat()
                    if timestamp(part.get("arrival_datetime"))
                    else None,
                )
            )
            coords = part.get("coordinates") or []
            if isinstance(coords, list) and len(coords) <= 20000:
                try:
                    geometry.extend(
                        point([p[1], p[0]])
                        for p in coords[:: max(1, math.ceil(len(coords) / 150))]
                    )
                except (ValueError, TypeError, IndexError):
                    geometry = []
        if not has_vehicle:
            continue
        choices.append(
            dict(
                minutes=math.ceil((arrive - depart).total_seconds() / 60),
                departure=depart.isoformat(),
                arrival=arrive.isoformat(),
                steps=steps,
                geometry=geometry[:3000],
                source="TransportAPI · "
                + clean(data.get("source", "Scheduled public transport"), 150),
                acknowledgements=clean(data.get("acknowledgements"), 1000),
            )
        )
    if not choices:
        return None
    # Arrive-by queries choose the latest usable complete journey; departing queries the earliest arrival.
    return (
        max(choices, key=lambda r: timestamp(r["departure"]))
        if arrive_by
        else min(choices, key=lambda r: timestamp(r["arrival"]))
    )


def route(a, b, deadline, account, *, arrive_by=None, depart_after=None):
    if (
        not all(account)
        or not a.get("point")
        or not b.get("point")
        or not (arrive_by or depart_after)
    ):
        return None
    instant = when(arrive_by or depart_after)
    if not instant:
        return None
    params = dict(
        from_=f"lonlat:{a['point'][1]:.6f},{a['point'][0]:.6f}",
        to=f"lonlat:{b['point'][1]:.6f},{b['point'][0]:.6f}",
        date=instant.strftime("%Y-%m-%d"),
        time=instant.strftime("%H:%M"),
        journey_time_type="arrive_by" if arrive_by else "leave_after",
    )
    params["from"] = params.pop("from_")
    headers = {"X-App-Id": account[0], "X-App-Key": account[1]}
    scope = hashlib.sha256(("\0".join(account)).encode()).hexdigest()
    try:
        data = travel_routes.cached(
            URL, params, deadline, 300, headers=headers, scope=scope
        )
        return parse(data, arrive_by, depart_after)
    except Exception:
        # Never expose a provider exception containing request headers/account credentials.
        return None
