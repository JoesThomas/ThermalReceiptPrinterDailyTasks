"""Fast, private dashboard snapshots; browsing never fetches external services."""
import json
from datetime import datetime, timezone
from pathlib import Path
from actions import checklists, delivery_state
from receipt.local_time import uk_receipt_time
from storage import write_json

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / 'data' / 'today_calendar.json'
CHANGES = ROOT / 'data' / 'receipt_changes.json'


def read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}


def save_calendar(events):
    rows = [{key: str(row.get(key, '')) for key in ('date', 'time', 'title', 'location')} for row in events]
    from receipt.freshness import snapshot
    check = snapshot().get('Calendar', {})
    write_json(CALENDAR, {'checked_at': check.get('source_checked_at') or check.get('checked_at') or datetime.now(timezone.utc).isoformat(),
                          'status': check.get('status', 'checked'), 'events': rows})


def snapshot_changes(pages):
    previous = read(CHANGES)
    state = previous.get('snapshot', {})
    if not isinstance(state, dict): state = {}
    state = {k: v for k, v in state.items() if (k in {'tasks', 'deliveries'} and isinstance(v, dict)) or (k == 'paid' and isinstance(v, list))}
    current = dict(state)
    changes = []
    if 'actions' in pages:
        tasks = {row['id']: row['title'] for row in checklists.rows('tasks') if not row['completed']}
        deliveries = {row['id']: row.get('expected', '') for row in delivery_state.checklist() if not row.get('confirmed')}
        current.update(tasks=tasks, deliveries=deliveries)
        if 'tasks' in state:
            changes.extend('New task: ' + title for key, title in tasks.items() if key not in state['tasks'])
        if 'deliveries' in state:
            changes.extend('Delivery timing changed: ' + when for key, when in deliveries.items()
                           if key in state['deliveries'] and state['deliveries'][key] != when)
            added = sum(key not in state['deliveries'] for key in deliveries)
            if added: changes.append(f'{added} new delivery notice(s)')
    from receipt.freshness import snapshot
    bank_status = snapshot().get('Bank transactions', {}).get('status')
    if 'finance' in pages and 'PAID [BANK MATCH]' in pages['finance'] and bank_status != 'unavailable':
        paid = pages['finance'].split('PAID [BANK MATCH]', 1)[1].split('PAID TOTAL', 1)[0]
        lines = [line.strip() for line in paid.splitlines() if '£' in line]
        current['paid'] = lines
        if 'paid' in state:
            changes.extend('New bank match: ' + line for line in lines if line not in state['paid'])
    write_json(CHANGES, {'snapshot': current, 'changes': changes,
                        'compared': bool(state), 'checked_at': datetime.now(timezone.utc).isoformat()})


def dashboard():
    errors = []
    try:
        tasks = [r for r in checklists.rows('tasks') if not r['completed'] and (not r.get('due') or r['due'] <= checklists.today())]
        from actions.receipt_workout import plan
        exercises = plan()
    except ValueError:
        tasks, exercises = [], []
        errors.append('Saved task lists could not be read.')
    calendar = read(CALENDAR)
    deliveries = [r for r in delivery_state.checklist() if not r.get('confirmed')]
    from receipt.capture import CAPTURE_FILE, LIVE_PREVIEW_FILE, load_capture
    checks = {}
    for path in (CAPTURE_FILE, LIVE_PREVIEW_FILE):
        for name, row in (load_capture(path) or {}).get('freshness', {}).items():
            if name not in checks or row['checked_at'] > checks[name]['checked_at']: checks[name] = row
    from services import bin_collections
    try: bin_state=bin_collections.load(); bin_lines=bin_collections.reminder_lines(bin_state)
    except ValueError: bin_lines=['Bin schedule unavailable']
    return dict(bin_lines=bin_lines, tasks=tasks, exercises=exercises, deliveries=deliveries,
                events=[e for e in calendar.get('events', []) if isinstance(e, dict) and e.get('date') == checklists.today()] if isinstance(calendar.get('events', []), list) else [],
                calendar_checked=uk_receipt_time(calendar.get('checked_at')),
                checks=[{'name': name, 'status': row['status'], 'local': uk_receipt_time(row.get('source_checked_at') or row['checked_at'])} for name, row in checks.items()],
                changes=read(CHANGES), errors=errors)
