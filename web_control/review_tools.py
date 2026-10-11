"""Authenticated aggregate finance history and manual rental accounting."""
from datetime import date
from flask import abort, flash, redirect, render_template, request, url_for
from finance import reviews, assets, rental_tax
from finance.money import parse
from receipt.local_time import uk_today


def register(app,login_required):
    @app.get('/finance/results')
    @login_required
    def finance_results_page():
        state=reviews.load();month=request.args.get('month',uk_today().strftime('%Y-%m'))
        try: date.fromisoformat(month+'-01')
        except ValueError:abort(400)
        tax=rental_tax.estimate(rental_tax.load())
        available=[row for row in state['rent_candidates'] if not any(entry.get('source_id')==row['id'] for entry in state['rent_entries'])]
        return render_template('finance_results.html',review_state=state,periods=reviews.period_review(state),
                               performance=reviews.rental_performance(state,month,tax),unfrozen_months=[(month,row) for month,row in sorted(state.get('month_observations',{}).items(),reverse=True) if month not in state['summaries']],properties=assets.load()['properties'],rent_candidates=available,today=uk_today())

    @app.post('/finance/results/savings')
    @login_required
    def confirm_period_savings():
        identity=request.form.get('period','');amount=parse(request.form.get('amount'))
        try:
            if amount is None or not 0<=amount<=10000000:raise ValueError('Enter the confirmed net salary-funded savings contribution')
            def change(state):
                if identity not in state['periods']:raise ValueError('Saved salary plan not found')
                state['periods'][identity].update(confirmed_savings=str(amount),savings_confirmed_on=uk_today().isoformat())
            reviews.store().update(change);flash('Savings contribution confirmed manually. Transfers and investment growth were not inferred.')
        except (ValueError,OSError) as error:flash(str(error))
        return redirect(url_for('finance_results_page'))

    @app.post('/finance/results/rental')
    @login_required
    def rental_entry_save():
        try:
            if request.form.get('action')=='delete':
                identity=request.form.get('id','')
                def remove(state):state['rent_entries']=[row for row in state['rent_entries'] if row['id']!=identity]
                reviews.store().update(remove)
            else:
                property_row=next((row for row in assets.load()['properties'] if row['id']==request.form.get('property')),None)
                if not property_row:raise ValueError('Choose a recorded property')
                source=request.form.get('candidate','')
                candidate=next((row for row in reviews.load()['rent_candidates'] if row['id']==source),None) if source else None
                if source and not candidate:raise ValueError('Rent candidate is no longer available; refresh Finance')
                reviews.add_entry(property_row,request.form.get('kind',''),request.form.get('date',''),request.form.get('amount',''),request.form.get('note','').strip(),candidate)
            flash('Private rental ledger updated. Annual tax inputs remain unchanged.')
        except (ValueError,OSError) as error:flash(str(error))
        return redirect(url_for('finance_results_page'))

    @app.post('/finance/results/freeze')
    @login_required
    def freeze_finance_summary():
        if request.form.get('confirm')!='on':abort(400)
        try:
            reviews.freeze(request.form.get('month',''))
            flash('Monthly summary frozen with its original coverage and assumptions; later refreshes cannot replace it.')
        except (ValueError,OSError) as error:flash(str(error))
        return redirect(url_for('finance_results_page'))
