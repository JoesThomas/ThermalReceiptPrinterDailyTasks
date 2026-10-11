"""Local setup guidance and date-based reminders, without remote API calls."""
from receipt.local_time import uk_now
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import flash, redirect, render_template, url_for
from finance.yearly_subscriptions import next_renewal

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}


def reminders(data=None, today=None):
    today = today or uk_now().date()
    data = data if data is not None else read(ROOT / 'data' / 'subscriptions.json')
    result = []
    for kind in ('monthly', 'yearly'):
        rows = data.get(kind, [])
        if not isinstance(rows, list): continue
        for row in rows:
            if not isinstance(row, dict): continue
            try: end = date.fromisoformat(row.get('end_date', ''))
            except (ValueError, TypeError): end = None
            if end and 0 <= (end - today).days <= 60:
                result.append({'name': row.get('name', 'Commitment'), 'date': end,
                               'kind': 'Contract ends', 'days': (end - today).days,
                               'anchor': 'commitments' if kind == 'monthly' else 'annual-subscriptions'})
            if kind == 'yearly':
                renewal = next_renewal(row, today)
                if renewal and (not end or renewal <= end) and 0 <= (renewal - today).days <= 30:
                    result.append({'name': row.get('name', 'Subscription'), 'date': renewal,
                                   'kind': 'Annual renewal', 'days': (renewal - today).days,
                                   'anchor': 'annual-subscriptions'})
    return sorted(result, key=lambda row: (row['date'], str(row['name']).casefold()))


def missing_dates(data):
    rows = data.get('yearly', [])
    if not isinstance(rows, list): return []
    return [str(row.get('name', 'Subscription')) for row in rows
            if isinstance(row, dict) and next_renewal(row) is None]


def checklist(root=ROOT):
    config = read(root / 'passwords.json')
    docs = config.get('google_docs', {})
    if not isinstance(docs, dict): docs = {}
    calendar = config.get('calendar', {})
    if not isinstance(calendar, dict): calendar = {}
    lists = read(root / 'data' / 'daily_lists.json')
    items = lists.get('items', [])
    if not isinstance(items, list): items = []
    bins = read(root / 'data' / 'bin_collections.json')
    subscriptions = read(root / 'data' / 'subscriptions.json')
    rows = [
        ('Location & weather', True, 'Review the location, forecast coordinates and local news feed.', 'index', 'settings', 'receipt-location'),
        ('Tasks', bool(docs.get('todo_url') or any(x.get('kind') == 'tasks' for x in items if isinstance(x, dict))), 'Add local tasks or configure your Google Doc.', 'task_list', '', ''),
        ('Exercises', bool(any(x.get('kind') == 'exercises' for x in items if isinstance(x, dict))), 'Add exercises and choose the equipment you can access. Bodyweight exercises can use no equipment.', 'exercise_list', '', ''),
        ('Calendar', bool(calendar.get('ical_url')), 'Set the private calendar iCal URL in passwords.json; use API health to check the connection.', 'calendar_map', '', ''),
        ('Bin collections', bool(bins.get('enabled') and (bins.get('uprn') or bins.get('manual'))), 'Choose your address or enter a manual collection schedule.', 'bin_settings', '', ''),
        ('Commitments', bool(subscriptions.get('monthly') or subscriptions.get('yearly')), 'Enter payment amounts, matching words and any renewal or contract end dates.', 'index', 'accounts', 'commitments'),
        ('Private backups', bool(list((root / 'data' / 'private_backups').glob('auto-*.json'))), 'Review daily snapshots and download a copy to keep elsewhere.', 'backup_page', '', ''),
    ]
    return [dict(name=name, configured=ready, description=description, endpoint=endpoint, view=view, anchor=anchor)
            for name, ready, description, endpoint, view, anchor in rows]


def register(app, login_required, root):
    @app.context_processor
    def reminder_context():
        return {'subscription_reminders': lambda: reminders(read(root / 'data' / 'subscriptions.json')),
                'subscription_missing_dates': lambda: missing_dates(read(root / 'data' / 'subscriptions.json'))}

    @app.get('/setup')
    @login_required
    def setup_page():
        from services.api_health import specifications, load
        checks=load().get('services', {})
        connections=[dict(name=spec[0],status=checks.get(spec[0],{}).get('status','Not checked')) for spec in specifications()] if 'api_health_check' in app.view_functions else []
        return render_template('setup.html', checklist=checklist(root),connections=connections)

    @app.post('/setup/printer-check')
    @login_required
    def setup_printer_check():
        from receipt.printer import readiness
        _, message = readiness()
        flash(message)
        return redirect(url_for('setup_page'))
