from flask import abort, redirect, render_template, request, url_for
from actions.delivery_state import checklist, confirm_delivery


def register(app, login_required):
    @app.get('/deliveries')
    @login_required
    def delivery_checklist():
        return render_template('deliveries.html', items=checklist())

    @app.post('/deliveries/confirm')
    @login_required
    def delivery_confirm():
        values = request.form.getlist('confirmed')
        if not values or any(value not in {'0', '1'} for value in values):
            abort(400)
        from actions.delivery_state import load_state
        key = request.form.get('id', '')
        before = load_state()['items'].get(key, {}).get('confirmed', False)
        if not confirm_delivery(key, '1' in values):
            abort(404)
        from web_control.undo import offer
        offer('delivery', key, before, '1' in values, 'delivery_checklist')
        return redirect(url_for('quick_actions') if request.form.get('return_quick') == '1' else url_for('index') if request.form.get('return_home') == '1' else url_for('delivery_checklist'))
