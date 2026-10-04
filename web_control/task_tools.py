import json
import re
from pathlib import Path
import requests
from flask import flash, redirect, render_template, request, url_for
from actions import checklists

ROOT = Path(__file__).resolve().parents[1]


def register(app, login_required):
    def display(kind):
        try:
            state = checklists.load()
            items = checklists.rows(kind)
        except ValueError as error:
            flash(str(error))
            items = []
            state = {'equipment': []}
        chosen = {row['id'] for row in checklists.exercise_plan(5)} if kind == 'exercises' and items else set()
        items = [{**row, 'on_receipt': row['id'] in chosen} for row in items]
        query = request.args.get('q', '').strip().lower()
        for row in items:
            row['display_title'] = checklists.exercise_title(row) if kind == 'exercises' else row['title']
            row['required'] = checklists.required_equipment(row) if kind == 'exercises' else []
            row['skipped'] = row.get('skipped_on') == checklists.today()
            row['group'] = 'Completed' if row['completed'] else ('Upcoming' if row.get('due', '') > checklists.today() else 'Today')
            row['overdue'] = bool(row.get('due') and row['due'] < checklists.today() and not row['completed'])
        items.sort(key=lambda row: (not row['on_receipt'], row['completed'], not row['overdue'],
                                   {'high': 0, 'normal': 1, 'low': 2}.get(row.get('priority', 'normal'), 1), row.get('due', '')))
        selected = [row for row in items if row['on_receipt'] and not row['skipped']]
        if query: items = [row for row in items if query in row['title'].lower()]
        return render_template('tasks.html', kind=kind, items=items,
                               done=sum(row['completed'] for row in items), selected=selected,
                               selected_done=sum(row['completed'] for row in selected),
                               equipment=checklists.EQUIPMENT, owned=state.get('equipment', []), query=query)

    @app.get('/tasks')
    @login_required
    def task_list():
        return display('tasks')

    @app.get('/exercises')
    @login_required
    def exercise_list():
        return display('exercises')

    @app.post('/lists/<kind>/update')
    @login_required
    def checklist_update(kind):
        try:
            checklists.update(kind, request.form.get('action', ''), request.form.get('id', ''), request.form.get('title', ''),
                              due=request.form.get('due', ''), priority=request.form.get('priority', 'normal'),
                              repeat=request.form.get('repeat', 'none'), equipment=None if request.form.get('action') == 'add' else request.form.getlist('equipment'),
                              sets=request.form.get('sets', '').strip(), reps=request.form.get('reps', '').strip(),
                              duration=request.form.get('duration', '').strip())
        except ValueError as error:
            flash(str(error))
        return redirect(url_for('index') if request.form.get('return_home') == '1' else url_for('exercise_list' if kind == 'exercises' else 'task_list'))

    @app.post('/exercises/plan')
    @login_required
    def exercise_workout():
        try:
            action = request.form.get('action')
            if action == 'equipment':
                checklists.save_equipment(request.form.getlist('equipment'))
                flash('Equipment saved. Suggest a workout to use it.')
            elif action == 'suggest':
                count = checklists.set_plan()
                flash(f'Today’s workout now has {count} matching exercises.' if count else 'No confirmed exercises match. Add exercises or set equipment requirements in the library.')
            elif action == 'choose':
                checklists.set_plan(request.form.getlist('exercise'))
                flash('Today’s exercises saved for the receipt.')
            else:
                raise ValueError('Unknown workout action.')
        except ValueError as error:
            flash(str(error))
        return redirect(url_for('exercise_list'))

    @app.post('/lists/<kind>/refresh')
    @login_required
    def checklist_refresh(kind):
        if kind not in {'tasks', 'exercises'}:
            return ('Unknown list', 404)
        try:
            private = json.loads((ROOT / 'passwords.json').read_text())
            value = private.get('google_docs', {}).get('todo_url' if kind == 'tasks' else 'random_url', '')
            document = value.split('/document/d/', 1)[-1].split('/', 1)[0] if '/document/d/' in value else value
            if not re.fullmatch(r'[A-Za-z0-9_-]+', document):
                raise ValueError()
            response = requests.get(f'https://docs.google.com/document/d/{document}/export?format=txt', timeout=15)
            response.raise_for_status()
            checklists.sync(response.text, kind)
            flash('Google Doc refreshed. Your local items and completion marks were kept.')
        except (OSError, ValueError, requests.RequestException):
            flash('Could not refresh the Google Doc. Your saved list is still available.')
        return redirect(url_for('exercise_list' if kind == 'exercises' else 'task_list'))
