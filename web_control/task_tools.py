import json
from datetime import date, timedelta
import re
from pathlib import Path
import requests
from flask import flash, redirect, render_template, request, url_for
from actions import checklists

ROOT = Path(__file__).resolve().parents[1]


def register(app, login_required):
    def display(kind, prep_draft=None):
        if kind == 'tasks':
            try:
                from services.vehicle_records import sync_mot_tasks
                sync_mot_tasks()
            except (OSError, ValueError):
                flash('MOT tasks could not be updated. Check saved vehicle dates and task data.')
        try:
            if kind == 'exercises':
                from actions.receipt_workout import plan
                receipt_plan = plan()
            state = checklists.load()
            items = [{**row, 'completed': checklists.is_done(row)} for row in state['items'] if row['kind'] == kind]
        except ValueError as error:
            flash(str(error))
            items = []
            state = {'equipment': []}
        chosen = {row['id'] for row in receipt_plan} if kind == 'exercises' and items else set()
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
        from actions.day_assistant import eligible_tasks, focus_for
        tomorrow = (date.fromisoformat(checklists.today())+timedelta(days=1)).isoformat()
        focus_options = [row for row in items if not row['completed'] and not row['skipped'] and row['group'] == 'Today']
        tomorrow_options = eligible_tasks(state, date.fromisoformat(tomorrow)) if kind == 'tasks' and 'items' in state else []
        if query: items = [row for row in items if query in row['title'].lower()]
        return render_template('tasks.html', kind=kind, items=items,
                               done=sum(row['completed'] for row in items), selected=selected,
                               additional_workout=checklists.exercise_plan(5) if kind == 'exercises' else [],
                               selected_done=sum(row['completed'] for row in selected),
                               equipment=checklists.EQUIPMENT, owned=state.get('equipment', []), query=query,
                               assistant=state.get('assistant', {}), assistant_day=checklists.today(),
                               focus_options=focus_options, prep_draft=prep_draft or {},
                               tomorrow_day=tomorrow, tomorrow_options=tomorrow_options,
                               today_focus=focus_for(state.get('assistant', {}), checklists.today()),
                               tomorrow_focus=focus_for(state.get('assistant', {}), tomorrow))

    @app.get('/tasks')
    @login_required
    def task_list():
        return display('tasks')

    @app.post('/tasks/focus')
    @login_required
    def task_focus():
        from actions.day_assistant import choose_focus
        try:
            today = date.fromisoformat(checklists.today())
            selected_day = date.fromisoformat(request.form.get('focus_day', ''))
            if selected_day not in (today, today+timedelta(days=1)):
                raise ValueError('The day changed. Refresh before choosing today’s priorities.')
            choose_focus(request.form.getlist('focus_task'), selected_day)
            flash(f'Do first choices saved for {selected_day.isoformat()}. Completed and skipped tasks stay off the receipt.')
        except ValueError as error:
            flash(str(error))
        return redirect(url_for('task_list')+'#daily-assistant')

    @app.post('/tasks/preparation')
    @login_required
    def task_preparation():
        from actions.day_assistant import save_preparation
        try:
            travel = request.form.get('travel_minutes', '').strip()
            remove = request.form.get('remove_rule', '')
            save_preparation(request.form.get('appointment_title', ''), int(travel) if travel and not remove else None,
                             [row.strip() for row in request.form.get('prep', '').splitlines() if row.strip()],
                             [row.strip() for row in request.form.get('bedtime', '').splitlines() if row.strip()] if 'bedtime' in request.form else None,
                             remove)
            flash('Daily preparation saved. Generate a fresh receipt to see it.')
        except ValueError as error:
            flash(str(error))
            return display('tasks', prep_draft=request.form.to_dict())
        return redirect(url_for('task_list')+'#daily-assistant')

    @app.get('/exercises')
    @login_required
    def exercise_list():
        return display('exercises')

    @app.post('/lists/<kind>/update')
    @login_required
    def checklist_update(kind):
        try:
            key = request.form.get('id', '')
            before, after = checklists.update(kind, request.form.get('action', ''), request.form.get('id', ''), request.form.get('title', ''),
                              due=request.form.get('due', ''), priority=request.form.get('priority', 'normal'),
                              repeat=request.form.get('repeat', 'none'), equipment=None if request.form.get('action') == 'add' else request.form.getlist('equipment'),
                              sets=request.form.get('sets', '').strip(), reps=request.form.get('reps', '').strip(),
                              duration=request.form.get('duration', '').strip())
            if before and request.form.get('action') == 'toggle':
                from web_control.undo import offer
                offer(kind, key, before, after, 'exercise_list' if kind == 'exercises' else 'task_list')
        except ValueError as error:
            flash(str(error))
        return redirect(url_for('quick_actions') if request.form.get('return_quick') == '1' else url_for('index') if request.form.get('return_home') == '1' else url_for('exercise_list' if kind == 'exercises' else 'task_list'))

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
                flash('Additional web workout saved. The receipt keeps its six-exercise rotation.')
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
