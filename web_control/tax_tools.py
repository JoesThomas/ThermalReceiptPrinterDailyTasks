"""Authenticated manual rental tax planning; no inference from net salary."""
from flask import flash, redirect, render_template, request, url_for
from finance import rental_tax


def register(app, login_required):
    @app.get('/finance/tax')
    @login_required
    def rental_tax_page():
        value = rental_tax.load()
        return render_template('rental_tax.html', tax_settings=value, rental_tax=rental_tax.estimate(value))

    @app.post('/finance/tax')
    @login_required
    def rental_tax_save():
        value = {key: request.form.get(key, '').strip() for key in rental_tax.FIELDS}
        value.update(enabled=request.form.get('enabled') == 'on', protect=request.form.get('protect') == 'on', year=request.form.get('year', ''), region=request.form.get('region', ''), method=request.form.get('method', 'expenses'))
        try:
            rental_tax.validate(value)
            rental_tax.store().update(lambda previous: (previous.clear(), previous.update(value)))
            flash('Private rental tax plan saved. Take-home salary is never used to infer your tax band.')
            return redirect(url_for('rental_tax_page'))
        except ValueError as error:
            return render_template('rental_tax.html', tax_settings=value, rental_tax=None, tax_error=str(error)), 400

    @app.context_processor
    def tax_context():
        try:
            return {'rental_tax': rental_tax.estimate(rental_tax.load())}
        except (ValueError, OSError):
            return {'rental_tax': None}
