"""Dated follow-ups, decisions and applications; never copies document contents."""
from datetime import date, datetime, timedelta
from pathlib import Path
import secrets
from actions.day_assistant import text, event_start
from storage import PrivateStore
from receipt.local_time import uk_today, UK

FILE = Path(__file__).resolve().parents[1] / 'data' / 'organiser.json'
KINDS = {'waiting': 'Waiting for', 'job': 'Job application', 'decision': 'Decision',
         'deposit': 'Deposit / money owed', 'refund': 'Refund', 'document': 'Document to bring'}


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('items'), list) or len(value['items']) > 500:
        raise ValueError('Invalid organiser data.')
    if type(value.get('travel_buffer')) is not int or not 0 <= value['travel_buffer'] <= 240:
        raise ValueError('Travel buffer must be between 0 and 240 minutes.')
    ids = set()
    for row in value['items']:
        if not isinstance(row, dict) or row.get('kind') not in KINDS or row.get('id') in ids or not isinstance(row.get('id'), str) or len(row['id']) != 24:
            raise ValueError('Invalid organiser item.')
        ids.add(row['id'])
        text(row.get('title'), 160)
        text(row.get('notes') or '-', 500)
        date.fromisoformat(row['due'])
        if type(row.get('done')) is not bool or not isinstance(row.get('documents'), list) or any(not isinstance(i, str) or len(i) != 32 for i in row['documents']):
            raise ValueError('Invalid item status or document link.')
        from finance.money import parse
        if row.get('amount') is not None and (parse(row['amount']) is None or not 0 <= parse(row['amount']) <= 10000000):
            raise ValueError('Enter a valid amount.')


def store():
    return PrivateStore(FILE, default=lambda: {'version': 1, 'travel_buffer': 30, 'items': []}, validate=validate)


def save_item(form, identifier=None):
    from finance.money import parse
    row = {'id': identifier or secrets.token_hex(12), 'kind': form.get('kind'), 'title': text(form.get('title', ''), 160),
           'notes': text(form.get('notes') or '-', 500), 'due': date.fromisoformat(form.get('due', '')).isoformat(),
           'done': form.get('done') == 'on', 'documents': form.getlist('document_id') if hasattr(form, 'getlist') else list(form.get('documents', [])),
           'amount': str(parse(form['amount'])) if form.get('amount') else None}
    def change(value):
        index = next((i for i, r in enumerate(value['items']) if r['id'] == row['id']), None)
        if identifier and index is None:
            raise ValueError('Item not found.')
        if index is None:
            value['items'].append(row)
        else:
            value['items'][index] = row
    store().update(change)


def update(identifier, action, new_date=None):
    def change(value):
        row = next((r for r in value['items'] if r['id'] == identifier), None)
        if row is None:
            raise ValueError('Item not found.')
        if action == 'delete':
            value['items'].remove(row)
        elif action == 'defer':
            row['due'] = date.fromisoformat(new_date).isoformat()
        elif action in ('done', 'reopen'):
            row['done'] = action == 'done'
        else:
            raise ValueError('Unknown action.')
    store().update(change)


def clashes(events, minutes=30, today=None):
    today = today or uk_today()
    entries = []
    for event in events:
        start = event_start(event)
        if not start or start.date() != today:
            continue
        end = event.get('end_dt')
        try:
            end = end if isinstance(end, datetime) else datetime.fromisoformat(end) if end else None
            if end and end.tzinfo is None:
                end = end.replace(tzinfo=UK)
        except (TypeError, ValueError):
            end = None
        entries.append((start, end, event))
    entries.sort(key=lambda row: row[0])
    warnings = []
    for i, (start, end, event) in enumerate(entries):
        if not end or end < start:
            continue  # Never invent appointment durations.
        for other_start, _, other in entries[i+1:]:
            gap = (other_start - end).total_seconds() / 60
            if gap < 0:
                warnings.append(f"Calendar overlap: {event.get('title', 'Appointment')} / {other.get('title', 'Appointment')}.")
            elif gap < minutes and event.get('location') and other.get('location') and event['location'].strip().casefold() != other['location'].strip().casefold():
                warnings.append(f"Only {int(gap)} minutes between {event.get('title', 'appointments')} and {other.get('title', 'the next appointment')}; check travel.")
    return warnings[:5]


def receipt_lines(events=(), today=None):
    today = today or uk_today()
    value = store().read()
    active = sorted((r for r in value['items'] if not r['done']), key=lambda r: (r['due'], r['title'].casefold()))
    selected = [r for r in active if date.fromisoformat(r['due']) <= today]
    if today.weekday() == 6:
        selected = [r for r in active if date.fromisoformat(r['due']) <= today + timedelta(days=7)]
    lines = clashes(events, value['travel_buffer'], today)
    for row in selected[:8]:
        lines.append(f"[ ] {KINDS[row['kind']]}: {row['title']} ({date.fromisoformat(row['due']):%d %b})")
        if row['documents'] or row['kind'] == 'document':
            lines.append('Bring required documents; open Organiser to view.')
    if today.weekday() == 6:
        upcoming = sorted((e for e in events if event_start(e) and today < event_start(e).date() <= today + timedelta(days=7)), key=event_start)
        for event in upcoming[:3]:
            start = event_start(event)
            lines.append(f"Next week {start:%a %H:%M}: {event.get('title', 'Appointment')}")
    if today.weekday() == 6 and active:
        from actions.checklists import rows
        open_tasks = [row for row in rows('tasks') if not row['completed']]
        if open_tasks:
            lines.append(f'Weekly task review: {len(open_tasks)} currently unfinished saved tasks.')
        lines.append(f"Sunday review: {len(active)} open items. Complete, defer or drop them in Organiser.")
    return lines
