from flask import flash, redirect, render_template, request, url_for
from finance import savings_goals as goals


def register(app,login_required,wealth_fn):
    def view():
        try:
            wealth=wealth_fn()
            return goals.review(wealth,request.args.get('tax_year') or None),None
        except (ValueError,OSError,KeyError,TypeError): return None,'Savings goals could not be loaded. Check the tax year or restore the private data.'

    @app.get('/savings/goals')
    @login_required
    def savings_goals_page():
        result,error=view()
        return render_template('savings_goals.html',goals=result,error=error,types=goals.TYPES,events=goals.EVENTS)

    @app.post('/savings/goals/account')
    @login_required
    def savings_goal_account():
        try:
            goals.account_settings(request.form.get('name',''),request.form.get('kind',''),request.form.get('type',''),request.form.get('target',''))
            flash('Account type and goal saved privately.')
        except (ValueError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'Account settings could not be saved.')
        return redirect(url_for('savings_goals_page'))

    @app.post('/savings/goals/contribution')
    @login_required
    def isa_contribution():
        try:
            name,kind=request.form.get('name',''),request.form.get('kind','')
            key=goals.identity(name,kind)
            if key not in goals.load()['accounts']:
                goals.account_settings(name,kind,request.form.get('type',''))
            goals.record(key,request.form.get('date',''),request.form.get('amount',''),request.form.get('event',''),request.form.get('id') or None)
            flash('ISA entry saved. Confirm tax-year completeness again after corrections.')
        except (ValueError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'Contribution could not be saved.')
        return redirect(url_for('savings_goals_page'))

    @app.post('/savings/goals/contribution/remove')
    @login_required
    def isa_contribution_remove():
        try: goals.remove(request.form.get('id',''));flash('ISA entry removed.')
        except (ValueError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'Entry could not be removed.')
        return redirect(url_for('savings_goals_page'))

    @app.post('/savings/goals/year')
    @login_required
    def isa_year_settings():
        try:
            goals.year_settings(request.form.get('year'),request.form.get('allowance'),request.form.get('cash_limit'),request.form.get('complete')=='on',request.form.get('first_payment') or None)
            flash('Tax-year preferences saved privately.')
        except (ValueError,TypeError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'Check the tax year and limits.')
        return redirect(url_for('savings_goals_page',tax_year=request.form.get('year')))

    @app.context_processor
    def goals_context():
        def summary(wealth):
            try: return goals.review(wealth)
            except (ValueError,OSError,KeyError,TypeError): return None
        return {'savings_goals_summary':summary}
