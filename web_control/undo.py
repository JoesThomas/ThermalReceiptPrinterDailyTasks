"""Short-lived undo with compare-and-swap checks against newer edits."""
import time
from flask import flash, redirect, request, session, url_for


def offer(kind, identity, before, after, destination):
    session['recent_undo'] = {'kind':kind,'id':identity,'before':before,'after':after,'expires':time.time()+30,'destination':destination}


def restore(value):
    kind = value['kind']; identity=value['id']
    if kind in ('tasks','exercises'):
        from actions import checklists
        with checklists.transaction() as state:
            row = next((row for row in state['items'] if row['id'] == identity and row['kind'] == kind), None)
            if row != value['after']: raise ValueError('The item changed again; undo was not applied.')
            if row is None:
                state['items'].append(value['before'])
            else:
                row.clear(); row.update(value['before'])
    elif kind == 'delivery':
        from actions import delivery_state
        with delivery_state.locked_state():
            state=delivery_state.load_state(); row=state['items'].get(identity)
            if not row or row.get('confirmed') != value['after']: raise ValueError('Delivery changed again; undo was not applied.')
            row['confirmed']=value['before']
            delivery_state.write_json(delivery_state.FILE,state)
    elif kind == 'delivery_status':
        from actions import delivery_state
        with delivery_state.locked_state():
            state=delivery_state.load_state()
            if state['items'].get(identity) != value['after']: raise ValueError('Delivery changed again; undo was not applied.')
            state['items'][identity]=value['before']
            delivery_state.write_json(delivery_state.FILE,state)
    elif kind == 'meal_plan':
        from meals import legacy_planner as meals
        from datetime import date
        path=meals.plan_path(meals.current_week_sunday(date.fromisoformat(identity)))
        if meals._load(path,None) != value['after']: raise ValueError('Meal plan changed again; undo was not applied.')
        meals._save(path,value['before'])
    elif kind == 'meal':
        from web_control import live_data
        data=live_data._read(live_data.MEALS_EATEN_FILE,{})
        if data.get(identity) != value['after']: raise ValueError('Meal confirmation changed again; undo was not applied.')
        if value['before'] is None: data.pop(identity,None)
        else: data[identity]=value['before']
        live_data._write(live_data.MEALS_EATEN_FILE,data)
    else: raise ValueError('Unknown undo action.')


def register(app,login_required):
    @app.context_processor
    def undo_context():
        value=session.get('recent_undo')
        return {'recent_undo':value if value and value['expires'] > time.time() else None}

    @app.post('/undo')
    @login_required
    def undo_recent():
        value=session.pop('recent_undo',None)
        if not value or value['expires'] <= time.time():
            flash('Undo expired. You can still edit the item directly.')
            return redirect(url_for('index'))
        try: restore(value); flash('Recent action undone.')
        except (ValueError,OSError) as error: flash(str(error))
        return redirect(url_for(value['destination']))
