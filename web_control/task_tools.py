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
            items = checklists.rows(kind)
        except ValueError as error:
            flash(str(error))
            items = []
        chosen = {row['id'] for row in checklists.exercise_plan(5)} if kind == 'exercises' and items else set()
        items = [{**row, 'on_receipt': row['id'] in chosen} for row in items]
        items.sort(key=lambda row: (not row['on_receipt'], row['completed']))
        return render_template('tasks.html', kind=kind, items=items,
                               done=sum(row['completed'] for row in items))

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
            checklists.update(kind, request.form.get('action', ''), request.form.get('id', ''), request.form.get('title', ''))
        except ValueError as error:
            flash(str(error))
        return redirect(url_for('exercise_list' if kind == 'exercises' else 'task_list'))

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
