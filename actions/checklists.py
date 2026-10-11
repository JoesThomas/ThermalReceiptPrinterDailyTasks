"""Private task/exercise lists, retaining whole Google Doc lines and local edits."""
import hashlib
import json
import random
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
from storage import write_json

FILE = Path(__file__).resolve().parents[1] / 'data' / 'daily_lists.json'


def today():
    return datetime.now(ZoneInfo('Europe/London')).date().isoformat()


EQUIPMENT = {'dumbbells': 'Dumbbells', 'rowing_machine': 'Rowing machine',
             'resistance_bands': 'Resistance bands', 'exercise_bike': 'Exercise bike',
             'pull_up_bar': 'Pull-up bar', 'barbell': 'Barbell', 'bench': 'Bench',
             'kettlebell': 'Kettlebell', 'treadmill': 'Treadmill', 'cable_machine': 'Cable machine',
             'exercise_mat': 'Exercise mat'}


def validate_state(value):
    if not isinstance(value, dict) or not isinstance(value.get('items'), list):
        raise ValueError('Saved checklist is invalid; restore it before editing.')
    for row in value['items']:
        if (not isinstance(row, dict) or row.get('kind') not in {'tasks', 'exercises'}
            or row.get('source') not in {'doc', 'local'}
            or not all(isinstance(row.get(key), str) for key in ('id', 'title'))
            or not isinstance(row.get('done'), bool)):
            raise ValueError('Saved checklist is invalid; restore it before editing.')
        if row.get('done_on') is not None:
            if not isinstance(row['done_on'], str):
                raise ValueError('Invalid completion date.')
            date.fromisoformat(row['done_on'])
    if not isinstance(value.get('equipment', []), list) or any(not isinstance(x, str) or x not in EQUIPMENT for x in value.get('equipment', [])):
        raise ValueError('Invalid saved equipment.')
    for row in value['items']:
        if not isinstance(row.get('priority', 'normal'), str) or row.get('priority', 'normal') not in {'high', 'normal', 'low'}:
            raise ValueError('Invalid priority.')
        if not isinstance(row.get('repeat', 'none'), str) or row.get('repeat', 'none') not in {'none', 'daily', 'weekly'}:
            raise ValueError('Invalid repeat setting.')
        if not isinstance(row.get('due', ''), str): raise ValueError('Invalid due date.')
        if row.get('due'):
            date.fromisoformat(row['due'])
        required = row.get('equipment', [])
        if not isinstance(required, list) or any(not isinstance(x, str) or x not in EQUIPMENT for x in required):
            raise ValueError('Invalid exercise equipment.')
        for field in ('sets', 'reps', 'duration'):
            if not isinstance(row.get(field, ''), str) or len(row.get(field, '')) > 40:
                raise ValueError('Invalid exercise instructions.')
    plan = value.get('plan', {})
    if not isinstance(plan, dict) or not isinstance(plan.get('ids', []), list) or any(not isinstance(x, str) for x in plan.get('ids', [])) or len(plan.get('ids', [])) > 5:
        raise ValueError('Invalid saved workout.')
    if not isinstance(plan.get('day', ''), str): raise ValueError('Invalid workout date.')
    if plan.get('day'): date.fromisoformat(plan['day'])
    for row in value['items']:
        history = row.get('history', [])
        if not isinstance(history, list) or len(history) > 90:
            raise ValueError('Invalid exercise history.')
        for day in history:
            if not isinstance(day, str): raise ValueError('Invalid exercise history.')
            date.fromisoformat(day)
        if row.get('skipped_on') is not None and not isinstance(row['skipped_on'], str): raise ValueError('Invalid skip date.')
        if row.get('skipped_on'): date.fromisoformat(row['skipped_on'])
    return value


def load():
    try:
        value = json.loads(FILE.read_text())
    except FileNotFoundError:
        return {'items': []}
    except (OSError, ValueError) as error:
        raise ValueError('Saved checklist could not be read; restore it before editing.') from error
    return validate_state(value)


@contextmanager
def transaction():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = load()
            yield state
            write_json(FILE, state)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def clean_lines(text, kind):
    result = []
    for raw in text.splitlines():
        raw = raw.lstrip('\ufeff').strip()
        if not raw or (kind == 'tasks' and not raw.endswith('.')):
            continue
        title = (raw[:-1].strip() if kind == 'tasks' else raw)[:240]
        if title and title not in result:
            result.append(title)
    return result


def sync(text, kind):
    titles = clean_lines(text, kind)[:500]
    with transaction() as state:
        previous = {row['id']: row for row in state['items']}
        state['items'] = [row for row in state['items'] if row['kind'] != kind or row['source'] != 'doc']
        for title in titles:
            key = hashlib.sha256((kind + ':' + title).encode()).hexdigest()
            row = previous.get(key, {'id': key, 'done': False, 'done_on': None})
            row.update(kind=kind, title=title, source='doc')
            state['items'].append(row)


def is_done(row, day=None):
    return row.get('done_on') == (day or today()) if row['kind'] == 'exercises' else bool(row.get('done')) and (row.get('repeat', 'none') == 'none' or not row.get('due') or row['due'] > (day or today()))


def rows(kind):
    return [{**row, 'completed': is_done(row)} for row in load()['items'] if row['kind'] == kind]


def update(kind, action, key='', title='', **metadata):
    if kind not in {'tasks', 'exercises'} or action not in {'add', 'save', 'toggle', 'delete', 'details', 'skip'}:
        raise ValueError('Unknown list action.')
    with transaction() as state:
        row = next((row for row in state['items'] if row['id'] == key and row['kind'] == kind), None)
        from copy import deepcopy
        before = deepcopy(row)
        if action == 'add':
            if len(state['items']) >= 500:
                raise ValueError('The list is full. Remove an item first.')
            row = {'id': uuid.uuid4().hex, 'kind': kind, 'source': 'local', 'done': False, 'done_on': None}
            state['items'].append(row)
        elif row is None:
            raise ValueError('This item has changed. Refresh the page.')
        if action in {'add', 'save'}:
            title = title.strip()
            if row['source'] != 'local' or not title or len(title) > 240 or any(ord(c) < 32 for c in title):
                raise ValueError('Enter a local item of up to 240 characters.')
            row['title'] = title.rstrip('.').strip() if kind == 'tasks' else title
            if not row['title']:
                raise ValueError('Enter a task name.')
        if action in {'add', 'save', 'details'}:
            if kind == 'tasks':
                due = metadata.get('due', '')
                if due: date.fromisoformat(due)
                row.update(due=due, priority=metadata.get('priority', 'normal'), repeat=metadata.get('repeat', 'none'))
            else:
                row.update(equipment=metadata.get('equipment') if metadata.get('equipment') is not None else required_equipment(row),
                           **{field: metadata.get(field, '') for field in ('sets', 'reps', 'duration')})
        if action == 'toggle':
            done = not is_done(row)
            if row.get('repeat', 'none') != 'none' and kind == 'tasks':
                if done:
                    row['previous_due'] = row.get('due', '')
                    row['due'] = (date.fromisoformat(today()) + timedelta(days=1 if row['repeat'] == 'daily' else 7)).isoformat()
                else:
                    row['due'] = row.pop('previous_due', '')
            row.update(done=done, done_on=today() if done else None)
            if kind == 'exercises':
                history = row.setdefault('history', [])
                if done and today() not in history: history.append(today())
                if not done and today() in history: history.remove(today())
                row['history'] = history[-90:]
                row.pop('skipped_on', None)
        elif action == 'skip':
            row['skipped_on'] = None if row.get('skipped_on') == today() else today()
        elif action == 'delete':
            if row['source'] != 'local':
                raise ValueError('Remove Google Doc items in the source document, then refresh.')
            state['items'].remove(row)
        validate_state(state)
        after = None if action == 'delete' else deepcopy(row)
    return before, after


def task_text(text):
    sync(text, 'tasks')
    return '\n'.join(row['title'] + '.' for row in rows('tasks') if not row['completed'] and row.get('skipped_on') != today() and (not row.get('due') or row['due'] <= today()))


def required_equipment(row):
    if 'equipment' in row:
        return row['equipment']
    title = row['title'].lower()
    matches = {'dumbbells': ('dumbbell', 'dumb bell'), 'rowing_machine': ('rowing', 'rower'),
               'resistance_bands': ('resistance band',), 'exercise_bike': ('exercise bike',),
               'pull_up_bar': ('pull-up', 'pull up'), 'barbell': ('barbell',), 'bench': ('bench press',),
               'kettlebell': ('kettlebell',), 'treadmill': ('treadmill',), 'cable_machine': ('cable ',)}
    return [key for key, words in matches.items() if any(word in title for word in words)]


def exercise_title(row):
    parts = [row['title']]
    if row.get('sets'): parts.append(row['sets'] + ' sets')
    if row.get('reps'): parts.append(row['reps'] + ' reps')
    if row.get('duration'): parts.append(row['duration'])
    return ' — '.join(parts)


def eligible(row, owned):
    confirmed = 'equipment' in row or bool(required_equipment(row))
    bodyweight = row['title'].lower().startswith(('squats', 'push-up', 'push up', 'plank', 'stretch', 'walking', 'walk '))
    return (confirmed or bodyweight) and set(required_equipment(row)) <= set(owned)


def exercise_plan(limit, day=None):
    day = day or today()
    state = load()
    available = sorted([row for row in state['items'] if row['kind'] == 'exercises'], key=lambda row: row['id'])
    plan = state.get('plan', {})
    if plan.get('day') == day:
        by_id = {row['id']: row for row in available}
        chosen = [by_id[key] for key in plan.get('ids', []) if key in by_id][:limit]
    else:
        if 'equipment' in state:
            available = [row for row in available if eligible(row, state['equipment'])]
        chosen = random.Random(day).sample(available, min(max(0, limit), len(available)))
    return [{**row, 'title': exercise_title(row), 'completed': is_done(row, day),
             'skipped': row.get('skipped_on') == day} for row in chosen if row.get('skipped_on') != day]


def save_equipment(equipment):
    with transaction() as state:
        state['equipment'] = sorted(set(equipment))
        validate_state(state)


def set_plan(ids=None):
    with transaction() as state:
        available = [row for row in state['items'] if row['kind'] == 'exercises']
        if ids is None:
            owned = set(state.get('equipment', []))
            available = [row for row in available if eligible(row, owned) and row.get('skipped_on') != today()]
            ids = [row['id'] for row in random.Random(today()).sample(available, min(5, len(available))) ]
        if len(ids) > 5 or any(key not in {row['id'] for row in available} for key in ids):
            raise ValueError('Choose up to five exercises from your library.')
        state['plan'] = {'day': today(), 'ids': list(dict.fromkeys(ids))}
        return len(ids)
