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
        if not confirm_delivery(request.form.get('id', ''), '1' in values):
            abort(404)
        return redirect(url_for('index') if request.form.get('return_home') == '1' else url_for('delivery_checklist'))
