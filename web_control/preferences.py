"""Authenticated private Away mode, retention and settings navigation."""
from flask import flash, redirect, render_template, request, url_for
from finance.credit_limits import summary
from receipt import lifestyle
from receipt.local_time import uk_today


def register(app, login_required, root):
    @app.get('/preferences')
    @login_required
    def preferences_page():
        from web_control.maintenance import saved
        from web_control.backup_health import state
        value = lifestyle.load()
        return render_template('preferences.html', preferences=value, away_active=lifestyle.active(settings=value), today=uk_today(), credit_cards=summary(value.get('credit_cards', [])), backup_health=state(root), backup_count=len(saved(root)))

    @app.post('/preferences/away')
    @login_required
    def away_save():
        try:
            away = {'enabled': request.form.get('enabled') == 'on', 'departure': request.form.get('departure', ''), 'return': request.form.get('return', ''), 'pause_meals': request.form.get('pause_meals') == 'on', 'travel_meals': list(dict.fromkeys(line.strip() for line in request.form.get('travel_meals', '').splitlines() if line.strip()))}
            lifestyle.store().update(lambda value: value.update(away=away))
            flash('Away mode saved. Meals resume on your return date; manual shopping items remain.')
        except ValueError as error: flash(str(error))
        return redirect(url_for('preferences_page'))

    @app.post('/preferences/cards')
    @login_required
    def credit_card_save():
        try:
            name = request.form.get('name', '').strip()
            def change(value):
                cards = [row for row in value.get('credit_cards', []) if row['name'].casefold() != name.casefold()]
                if request.form.get('action') != 'delete':
                    cards.append({'name':name,'limit':request.form.get('limit',''),'used':request.form.get('used','').strip() or None,'provider':request.form.get('provider','OTHER'),'as_of':uk_today().isoformat()})
                value['credit_cards'] = cards
            lifestyle.store().update(change)
            flash('Credit card details saved. Credit capacity is excluded from cash and runway.')
        except ValueError as error: flash(str(error))
        return redirect(url_for('preferences_page')+'#credit-cards')

    @app.post('/preferences/retention')
    @login_required
    def retention_save():
        try:
            periods = {key: int(request.form.get(key, '0')) for key in ('receipts', 'details')}
            lifestyle.store().update(lambda value: value.update(retention=periods))
            flash('Retention saved. Automatic cleanup applies while the server runs; financial ledgers, settings and backups are retained.')
        except ValueError as error: flash(str(error))
        return redirect(url_for('preferences_page'))

    @app.context_processor
    def shared_preferences():
        try:
            value = lifestyle.load()
            result = {'away_preferences': value['away'], 'away_active': lifestyle.active(settings=value)}
            if request.endpoint in ('meals_page', 'tesco_list'):
                from meals.legacy_planner import load_plan_for
                plan = load_plan_for(uk_today()) or {}
                result.update(away_excluded=plan.get('away_excluded', []), away_excluded_ingredients=plan.get('away_excluded_ingredients', []))
            return result
        except ValueError: return {'away_preferences': {}, 'away_active': False}
