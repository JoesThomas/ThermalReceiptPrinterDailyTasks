from datetime import datetime
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, url_for
from finance import premium_bonds as bonds

def register(app, login_required):
    def today():
        return datetime.now(ZoneInfo('Europe/London')).date()

    @app.get('/premium-bonds')
    @login_required
    def premium_bonds_page():
        try:
            result = bonds.review(today(), request.args.get('year'))
        except (ValueError, OSError):
            return 'Premium Bonds history could not be loaded. Check the year and private data file.', 400
        return render_template('premium_bonds.html', bonds=result, today=today())

    @app.post('/premium-bonds/record')
    @login_required
    def premium_bonds_record():
        try:
            bonds.record(request.form.get('kind'), request.form.get('date'), request.form.get('amount'), today())
            flash('Premium Bonds record saved locally.')
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Could not save the private record.')
        return redirect(url_for('premium_bonds_page'))

    @app.post('/premium-bonds/remove')
    @login_required
    def premium_bonds_remove():
        try:
            bonds.remove(request.form.get('kind'), request.form.get('id'))
            flash('Record removed. Excluded bank imports stay excluded on refresh.')
        except (ValueError, OSError):
            abort(400)
        return redirect(url_for('premium_bonds_page'))

    @app.post('/premium-bonds/confirm')
    @login_required
    def premium_bonds_confirm():
        if request.form.get('complete') != 'on':
            abort(400)
        try:
            bonds.confirm(request.form.get('year'), today())
        except (ValueError, TypeError, OSError):
            abort(400)
        return redirect(url_for('premium_bonds_page', year=request.form['year']))
