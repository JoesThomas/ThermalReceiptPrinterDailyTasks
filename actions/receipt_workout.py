"""A bounded, date-stable receipt rotation with editable starting targets."""
from datetime import date
from actions import checklists

PRESETS = (
    ('bicep_curls', 'Bicep curls', ['dumbbells'], '2', '10', ''),
    ('shrugs', 'Shrugs', ['dumbbells'], '2', '10', ''),
    ('situps', 'Sit-ups', [], '2', '10', ''),
    ('press_ups', 'Press-ups', [], '2', '8', ''),
    ('rowing', 'Rowing', ['rowing_machine'], '', '', '15 min, steady pace'),
    ('jogging', 'Jogging', [], '', '', '20 min, easy; walk breaks OK'),
)
ANCHOR = date(2026, 10, 6)


def ensure_presets():
    """Add private editable rows without deleting the user's exercise library."""
    with checklists.transaction() as state:
        for key, title, equipment, sets, reps, duration in PRESETS:
            identifier = 'receipt-exercise-' + key
            if any(row['id'] == identifier for row in state['items']):
                continue
            if len(state['items']) >= 500:
                raise ValueError('Exercise library is full; remove unused items to add the receipt routine.')
            state['items'].append(dict(id=identifier, title=title, equipment=equipment,
                                      sets=sets, reps=reps, duration=duration,
                                      kind='exercises', source='local', done=False, done_on=None))
        checklists.validate_state(state)


def plan(day=None):
    day = day or checklists.today()
    on = date.fromisoformat(day)
    ensure_presets()
    state = checklists.load()
    phase = (on - ANCHOR).days % 4
    keys = ['bicep_curls', 'shrugs', 'situps', 'press_ups'] if phase % 2 == 0 else ['rowing' if phase == 1 else 'jogging']
    owned = state.get('equipment')
    # Without a configured equipment list, show equipment needs on the receipt.
    if keys == ['rowing'] and owned is not None and 'rowing_machine' not in owned:
        keys = ['jogging']
    by_id = {row['id']: row for row in state['items'] if row['kind'] == 'exercises'}
    selected = []
    for key, title, required, *_ in PRESETS:
        if key not in keys or owned is not None and not set(required) <= set(owned):
            continue
        row = by_id['receipt-exercise-' + key]
        if row.get('skipped_on') == day:
            continue
        # Titles and equipment are fixed; targets remain editable in the UI.
        selected.append({**row, 'title': checklists.exercise_title({**row, 'title': title}),
                         'required': required, 'completed': checklists.is_done(row, day), 'skipped': False})
    return selected
