"""Dated nearby music listings from Ticketmaster; shared by web and receipt."""
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from threading import RLock
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from zoneinfo import ZoneInfo

CONFIG_FILE = Path(__file__).resolve().parents[1] / 'data' / 'local_gigs_config.json'
_CACHE = {}
_LOCK = RLock()


def api_key():
    key = os.environ.get('TICKETMASTER_API_KEY', '').strip()
    if key:
        return key
    try:
        return str(json.loads(CONFIG_FILE.read_text(encoding='utf-8')).get('api_key', '')).strip()
    except (ValueError, OSError, AttributeError):
        return ''


def options():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        radius, limit = int(data.get('radius_km',25)), int(data.get('receipt_limit',8))
        if not 1 <= radius <= 100 or not 1 <= limit <= 30:
            raise ValueError()
        return {'radius_km':radius, 'receipt_limit':limit, 'enabled':bool(data.get('enabled',True))}
    except (ValueError, OSError, AttributeError, TypeError):
        return {'radius_km':25,'receipt_limit':8,'enabled':True}


def save_options(radius, limit, enabled, key='', clear=False):
    if not 1 <= radius <= 100 or not 1 <= limit <= 30:
        raise ValueError('Choose a radius of 1–100 km and 1–30 receipt listings.')
    if os.environ.get('TICKETMASTER_API_KEY') and (key.strip() or clear):
        raise ValueError('The API key is managed by the server environment.')
    key = key.strip()
    if key and (len(key) > 200 or not key.isalnum()):
        raise ValueError('Enter a valid Ticketmaster API key.')
    with _LOCK:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            if not isinstance(data,dict):
                data = {}
        except (ValueError,OSError):
            data = {}
        data.update(radius_km=radius,receipt_limit=limit,enabled=enabled)
        if clear:
            data.pop('api_key',None)
        elif key:
            data['api_key'] = key
        from storage import write_json
        write_json(CONFIG_FILE, data)
        _CACHE.clear()


def save_api_key(key, clear=False):
    current = options()
    save_options(current['radius_km'],current['receipt_limit'],current['enabled'],key,clear)


def geohash(latitude, longitude):
    alphabet = '0123456789bcdefghjkmnpqrstuvwxyz'
    ranges = [[-180., 180.], [-90., 90.]]
    coordinates = [longitude, latitude]
    result, number = '', 0
    for bit in range(45):
        axis = bit % 2
        midpoint = sum(ranges[axis]) / 2
        high = coordinates[axis] >= midpoint
        number = number * 2 + int(high)
        ranges[axis][0 if high else 1] = midpoint
        if bit % 5 == 4:
            result += alphabet[number]
            number = 0
    return result


def _distance(lat, lon, location):
    a, b = math.radians(float(lat)), math.radians(float(location['latitude']))
    delta_lat = b - a
    delta_lon = math.radians(float(location['longitude']) - float(lon))
    value = math.sin(delta_lat / 2)**2 + math.cos(a)*math.cos(b)*math.sin(delta_lon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, value))))


def normalise(events, on, location, radius):
    result, seen = [], set()
    for event in events:
        dates = event.get('dates', {})
        start = dates.get('start', {})
        if start.get('localDate') != on.isoformat() or start.get('dateTBD') or start.get('dateTBA'):
            continue
        if dates.get('status', {}).get('code') in {'cancelled', 'postponed'}:
            continue
        if not any(c.get('segment', {}).get('name', '').casefold() == 'music' for c in event.get('classifications', [])):
            continue
        venue = (event.get('_embedded', {}).get('venues') or [{}])[0]
        coords = venue.get('location', {})
        distance = None
        try:
            distance = _distance(coords['latitude'], coords['longitude'], location)
            if not math.isfinite(distance) or distance > radius:
                continue
        except (KeyError, ValueError, TypeError):
            pass
        name = str(event.get('name', '')).strip()
        venue_name = str(venue.get('name') or 'Venue not supplied')
        clock = start.get('localTime', '')[:5]
        if start.get('timeTBA') or start.get('noSpecificTime') or not clock:
            clock = ''
        identity = (name.casefold(), venue_name.casefold(), clock)
        if not name or identity in seen:
            continue
        seen.add(identity)
        url = str(event.get('url', ''))
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username:
            url = ''
        result.append({'name':name, 'venue':venue_name, 'time':clock, 'url':url,
                       'distance':round(distance,1) if distance is not None else None})
    return sorted(result, key=lambda r:(r['time'] or '99:99', r['venue'].casefold(), r['name'].casefold()))


def get_gigs(location, on, radius=25):
    key = api_key()
    result = {'events':[], 'date':on, 'location':location['name'], 'radius':radius,
              'status':'not_configured', 'checked_at':None, 'truncated':False}
    if not key:
        return result
    identity = (on.isoformat(), float(location['latitude']), float(location['longitude']), radius,
                hashlib.sha256(key.encode()).hexdigest())
    with _LOCK:
        cached = _CACHE.get(identity)
        if cached and time.monotonic() - cached[0] < 900:
            return dict(cached[1], location=location['name'])
        params = {'apikey':key, 'geoPoint':geohash(float(location['latitude']),float(location['longitude'])),
                  'radius':radius, 'unit':'km', 'classificationName':'Music', 'size':200,
                  'localStartDateTime':f'{on.isoformat()}T00:00:00,{on.isoformat()}T23:59:59',
                  'includeTBA':'no', 'includeTBD':'no', 'sort':'date,asc'}
        raw, status = [], 'ok'
        # Bound receipt generation time: one request normally, at most two pages.
        for page in range(2):
            try:
                url = 'https://app.ticketmaster.com/discovery/v2/events.json?' + urlencode(dict(params,page=page))
                with urlopen(url, timeout=5) as response:
                    payload = json.loads(response.read(2_000_001))
                raw.extend(payload.get('_embedded', {}).get('events', []))
                pages = int(payload.get('page', {}).get('totalPages', 1))
                if pages <= page + 1:
                    break
                if page == 1:
                    result['truncated'] = True
            except Exception:
                # Do not expose request URLs or API keys through errors/logs.
                status = 'partial' if raw else 'unavailable'
                break
        result.update(events=normalise(raw,on,location,radius), status=status,
                      checked_at=datetime.now(ZoneInfo('Europe/London')))
        # Shorter retry interval after a provider failure.
        stored_at = time.monotonic() - (840 if status != 'ok' else 0)
        if len(_CACHE) >= 32:
            _CACHE.clear()
        _CACHE[identity] = (stored_at, result)
        return result


def receipt_lines(result, limit=8):
    from textwrap import wrap
    if result["status"] == "ok" and not result["events"] and not result["truncated"]:
        return []
    lines = ['GIGS TODAY', '-'*40, f"{result['location']} / {result['radius']} KM"]
    if result['status'] == 'not_configured':
        lines.append('SET UP TICKETMASTER IN WEB GIGS PAGE')
    elif result['status'] == 'unavailable':
        lines.append('GIG LISTINGS CURRENTLY UNAVAILABLE')
    elif not result['events']:
        lines.append('NO MATCHING GIGS IN THIS SOURCE')
    for event in result['events'][:limit]:
        lines.append((event['time'] or 'TIME TBC') + ' ' + event['name'])
        lines.append('  ' + event['venue'])
    if len(result['events']) > limit:
        lines.append(f"+{len(result['events'])-limit} MORE ON WEB GIGS PAGE")
    if result['status'] == 'partial' or result['truncated']:
        lines.append('LISTINGS INCOMPLETE')
    lines.append('TICKETMASTER LISTINGS / CHECK DETAILS')
    lines.append('-'*40)
    return [part for line in lines for part in wrap(line,width=40)]
