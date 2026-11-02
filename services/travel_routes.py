"""Explicit, cached Photon / FOSSGIS lookups; no traffic or transit timetable claims."""

import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import requests
from storage import PrivateStore, file_lock
from services.day_travel import point

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "day_travel"
USER_AGENT = "ThermalReceiptPrinterDailyTasks/1.0 (+https://github.com/JoesThomas/ThermalReceiptPrinterDailyTasks)"


def endpoint(name, default):
    url = os.environ.get(name, default).rstrip("/")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Travel provider must use an HTTPS base URL without credentials or query parameters."
        )
    return url


def fetch(url, params, deadline):
    """One installation-wide request per second; explicit user jobs only."""
    CACHE.mkdir(parents=True, exist_ok=True)
    with file_lock(CACHE / "request-rate"):
        rate = PrivateStore(CACHE / "rate.json", default=dict, max_bytes=1000)
        previous = rate.read().get("last", 0)
        delay = max(0, min(1.05, 1.05 - (time.time() - previous)))
        if time.monotonic() + delay >= deadline:
            raise ValueError("Travel lookup time limit reached.")
        if delay:
            time.sleep(delay)
        rate.update(lambda v: v.update(last=time.time()))
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=(3, min(6, max(1, deadline - time.monotonic()))),
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    raise ValueError("Travel provider unavailable.")
                data = []
                size = 0
                for chunk in response.iter_content(16384):
                    size += len(chunk)
                    if size > 800000 or time.monotonic() > deadline:
                        raise ValueError("Travel response limit reached.")
                    data.append(chunk)
                return json.loads(b"".join(data))
            finally:
                response.close()


def cached(url, params, deadline, ttl):
    digest = hashlib.sha256(
        json.dumps([url, params], sort_keys=True).encode()
    ).hexdigest()
    path = CACHE / (digest + ".json")
    item = PrivateStore(path, default=dict, max_bytes=900000)
    saved = item.read()
    if 0 <= time.time() - saved.get("at", 0) < ttl:
        return saved["data"]
    data = fetch(url, params, deadline)
    item.update(lambda v: v.update(at=time.time(), data=data))
    # Hard cap on private cache, with no address in filenames/logs.
    rows = sorted(CACHE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in rows[500:]:
        old.unlink(missing_ok=True)
    return data


def locate(address, deadline):
    url = endpoint("RECEIPT_TRAVEL_GEOCODER", "https://photon.komoot.io") + "/api/"
    data = cached(url, {"q": address, "limit": 3, "lang": "en"}, deadline, 30 * 86400)
    result = []
    for row in data.get("features", [])[:3]:
        try:
            lon, lat = row["geometry"]["coordinates"]
            p = point([lat, lon])
            props = row["properties"]
            label = ", ".join(
                str(props[k])
                for k in (
                    "name",
                    "housenumber",
                    "street",
                    "postcode",
                    "city",
                    "state",
                    "country",
                )
                if props.get(k)
            )[:500]
            result.append(dict(point=p, label=label or address))
        except (ValueError, TypeError, KeyError):
            continue
    return result


def route(a, b, mode, deadline):
    if mode not in {"driving", "walking", "cycling"}:
        return None
    profile = {"driving": "car", "walking": "foot", "cycling": "bike"}[mode]
    base = endpoint("RECEIPT_TRAVEL_ROUTER", "https://routing.openstreetmap.de")
    coords = ";".join(f"{p[1]:.6f},{p[0]:.6f}" for p in (a["point"], b["point"]))
    # Each routed-* server has its own loaded profile; the API path label is driving.
    url = base + f"/routed-{profile}/route/v1/driving/" + coords
    try:
        data = cached(
            url,
            {"overview": "simplified", "geometries": "geojson", "steps": "false"},
            deadline,
            86400,
        )
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        result = data["routes"][0]
        seconds = result.get("duration")
        if (
            type(seconds) not in (int, float)
            or not math.isfinite(seconds)
            or not 0 <= seconds <= 7 * 86400
        ):
            return None
        geometry = result.get("geometry", {}).get("coordinates", [])
        if not isinstance(geometry, list) or len(geometry) > 20000:
            return None
        points = [point([p[1], p[0]]) for p in geometry]
        return dict(
            minutes=math.ceil(seconds / 60),
            geometry=points,
            source="FOSSGIS / OSRM estimate; no live traffic",
        )
    except (
        OSError,
        ValueError,
        requests.RequestException,
        TypeError,
        KeyError,
        IndexError,
    ):
        return None
