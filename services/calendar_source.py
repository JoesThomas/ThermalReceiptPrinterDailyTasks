"""Parse recurrence in a disposable worker so malformed calendars cannot stall jobs."""
import json
import subprocess
import sys
import time as clock
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path


def parse(content, today, days):
    from icalendar import Calendar
    import recurring_ical_events
    calendar = Calendar.from_ical(content)
    tz = ZoneInfo('Europe/London')
    events = recurring_ical_events.of(calendar).between(datetime.combine(today, time.min),
                                                       datetime.combine(today + timedelta(days=days), time.max))
    results = []
    for event in events:
        start = event.get('DTSTART'); end = event.get('DTEND')
        if start is None: continue
        sv = start.dt; ev = end.dt if end is not None else None
        all_day = isinstance(sv, date) and not isinstance(sv, datetime)
        if all_day: event_date, label, start_dt, end_dt = sv, 'ALL DAY', None, None
        else:
            sv = sv.replace(tzinfo=tz) if sv.tzinfo is None else sv.astimezone(tz)
            if isinstance(ev, datetime): ev = ev.replace(tzinfo=tz) if ev.tzinfo is None else ev.astimezone(tz)
            event_date, label, start_dt = sv.date(), sv.strftime('%H:%M'), sv
            end_dt = ev if isinstance(ev, datetime) else sv
            if end_dt != sv: label += '-' + end_dt.strftime('%H:%M')
        results.append(dict(date=event_date, time=label, title=str(event.get('SUMMARY','UNTITLED EVENT')),
                            location=str(event.get('LOCATION','') or '').strip(), start_dt=start_dt, end_dt=end_dt, all_day=all_day))
        if len(results) > 2000: raise ValueError('Too many calendar events')
    return sorted(results, key=lambda x:(x['date'],x['time']))


def collect(url, today, days):
    from services.api_health import observed_request
    from services.source_cache import decode
    deadline = clock.monotonic() + 12
    response = observed_request('Google Calendar','get',url,timeout=(3,5),stream=True)
    try:
        response.raise_for_status(); chunks = []; size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000 or clock.monotonic() > deadline: raise ValueError('Calendar download limit reached')
            chunks.append(chunk)
        content = b''.join(chunks).decode('utf-8-sig')
    finally: response.close()
    worker = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                            input=json.dumps({'content':content,'today':today.isoformat(),'days':days}, ensure_ascii=False),
                            capture_output=True, text=True, timeout=8)
    if worker.returncode: raise ValueError('Calendar parsing failed')
    return decode(json.loads(worker.stdout))


if __name__ == '__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from services.source_cache import encode
    value = json.loads(sys.stdin.read(4_000_000))
    print(json.dumps(encode(parse(value['content'],date.fromisoformat(value['today']),value['days']))))
