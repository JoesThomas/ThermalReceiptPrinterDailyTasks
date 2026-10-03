"""Private task/exercise lists, retaining whole Google Doc lines and local edits."""
import hashlib
import json
import random
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
from storage import write_json

FILE = Path(__file__).resolve().parents[1] / 'data' / 'daily_lists.json'


def today():
    return datetime.now(ZoneInfo('Europe/London')).date().isoformat()


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
            from datetime import date
            if not isinstance(row['done_on'], str):
                raise ValueError('Invalid completion date.')
            date.fromisoformat(row['done_on'])
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
    return row.get('done_on') == (day or today()) if row['kind'] == 'exercises' else bool(row.get('done'))


def rows(kind):
    return [{**row, 'completed': is_done(row)} for row in load()['items'] if row['kind'] == kind]


def update(kind, action, key='', title=''):
    if kind not in {'tasks', 'exercises'} or action not in {'add', 'save', 'toggle', 'delete'}:
        raise ValueError('Unknown list action.')
    with transaction() as state:
        row = next((row for row in state['items'] if row['id'] == key and row['kind'] == kind), None)
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
        elif action == 'toggle':
            done = not is_done(row)
            row.update(done=done, done_on=today() if done else None)
        elif action == 'delete':
            if row['source'] != 'local':
                raise ValueError('Remove Google Doc items in the source document, then refresh.')
            state['items'].remove(row)


def task_text(text):
    sync(text, 'tasks')
    return '\n'.join(row['title'] + '.' for row in rows('tasks') if not row['completed'])


def exercise_plan(limit, day=None):
    day = day or today()
    available = sorted(rows('exercises'), key=lambda row: row['id'])
    chosen = random.Random(day).sample(available, min(max(0, limit), len(available)))
    return [{**row, 'completed': is_done(row, day)} for row in chosen]
