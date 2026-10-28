"""Fast, private dashboard snapshots; browsing never fetches external services."""
from datetime import datetime, timezone
from pathlib import Path
from actions import checklists, delivery_state
from receipt.local_time import uk_receipt_time
from storage import write_json

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / 'data' / 'today_calendar.json'
CHANGES = ROOT / 'data' / 'receipt_changes.json'


from storage import read_json_object as read


def save_calendar(events):
    rows = [{**{key: str(row.get(key, '')) for key in ('uid', 'date', 'time', 'title', 'location', 'source', 'fixture_id', 'competition')},
             'start_dt': row['start_dt'].isoformat() if isinstance(row.get('start_dt'), datetime) else row.get('start_dt'),
             'end_dt': row['end_dt'].isoformat() if isinstance(row.get('end_dt'), datetime) else row.get('end_dt'),
             'all_day': bool(row.get('all_day'))} for row in events]
    from receipt.freshness import snapshot
    check = snapshot().get('Calendar agenda', snapshot().get('Calendar', {}))
    write_json(CALENDAR, {'checked_at': check.get('source_checked_at') or check.get('checked_at') or datetime.now(timezone.utc).isoformat(),
                          'status': check.get('status', 'checked'), 'warnings': check.get('warnings', []), 'events': rows})


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
        from services.vehicle_records import sync_mot_tasks
        sync_mot_tasks()
    except (OSError, ValueError):
        errors.append('MOT tasks could not be updated; check saved vehicle dates and task data.')
    list_state = {'items': []}
    try:
        list_state = checklists.load()
        task_rows = [{**row, 'completed': checklists.is_done(row)} for row in list_state['items'] if row['kind'] == 'tasks']
        tasks = [r for r in task_rows if not r['completed'] and r.get('skipped_on') != checklists.today() and (not r.get('due') or r['due'] <= checklists.today())]
        from actions.receipt_workout import plan
        exercises = plan()
    except ValueError:
        tasks, exercises = [], []
        errors.append('Saved task lists could not be read.')
    calendar = read(CALENDAR)
    errors.extend(str(w) for w in calendar.get('warnings', []) if isinstance(w, str))
    deliveries = [r for r in delivery_state.checklist() if not r.get('confirmed') and not r.get('dismissed') and r.get('skipped_on') != checklists.today()]
    from receipt.capture import CAPTURE_FILE, LIVE_PREVIEW_FILE, load_capture
    checks = {}
    for path in (CAPTURE_FILE, LIVE_PREVIEW_FILE):
        for name, row in (load_capture(path) or {}).get('freshness', {}).items():
            if name not in checks or row['checked_at'] > checks[name]['checked_at']: checks[name] = row
    from services import bin_collections
    try: bin_state=bin_collections.load(); bin_lines=bin_collections.reminder_lines(bin_state)
    except ValueError: bin_lines=['Bin schedule unavailable']
    from actions.day_assistant import briefing
    assistant = dict(focus=[], appointment=None, bedtime=[])
    try:
        assistant = briefing(list_state, calendar.get('events', []))
    except (OSError, ValueError):
        errors.append('Daily assistant settings unavailable.')
    focus_ids = {row['id'] for row in assistant['focus']}
    tasks = [row for row in tasks if row['id'] not in focus_ids]
    from actions import birthdays
    try: birthday_rows = birthdays.upcoming()
    except (OSError, ValueError):
        birthday_rows = []
        errors.append('Birthday data unavailable; review the birthday list.')
    from web_control.daily_focus import build as build_focus
    from services.vehicle_records import load as load_vehicles
    from finance.check_changes import view as finance_changes
    try: vehicle_rows=load_vehicles()['vehicles']
    except (ValueError,OSError): vehicle_rows=[]
    focus=build_focus(datetime.fromisoformat(checklists.today()).date(),tasks,assistant,bin_lines,vehicle_rows,birthday_rows,finance_changes())
    return dict(priorities=focus,birthdays=birthday_rows, assistant=assistant, bin_lines=bin_lines, tasks=tasks, exercises=exercises, deliveries=deliveries,
                events=[e for index, e in enumerate(calendar.get('events', [])) if isinstance(e, dict) and e.get('date') == checklists.today() and (not assistant['appointment'] or index != assistant['appointment']['index'])] if isinstance(calendar.get('events', []), list) else [],
                calendar_checked=uk_receipt_time(calendar.get('checked_at')),
                checks=[{'name': name, 'status': row['status'], 'local': uk_receipt_time(row.get('source_checked_at') or row['checked_at'])} for name, row in checks.items()],
                changes=read(CHANGES), errors=errors)
