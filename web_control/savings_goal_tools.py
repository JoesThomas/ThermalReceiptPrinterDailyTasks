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

    @app.post('/savings/isa/create')
    @login_required
    def isa_create():
        try:
            from finance import wealth_history
            name=request.form.get('name','').strip()
            account_type=request.form.get('type','')
            if account_type not in goals.ISA: raise ValueError('Choose an adult ISA type.')
            kind='investment' if account_type != 'cash_isa' else 'savings'
            on=request.form.get('date','')
            from datetime import date
            parsed=date.fromisoformat(on)
            balance=wealth_history.amount(request.form.get('balance',''))
            if parsed>goals.today() or parsed.year<2000: raise ValueError('Choose a date no later than today.')
            if goals.identity(name,kind) in goals.load()['accounts']: raise ValueError('This account already exists. Update its balance below.')
            goals.account_settings(name,kind,account_type)
            wealth_history.record(name,kind,on,balance,today=goals.today())
            flash('ISA created privately. Add its dated payments and interest below; the opening balance is not treated as a new contribution.')
        except (ValueError,TypeError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'ISA could not be created.')
        return redirect(url_for('savings_goals_page'))

    @app.post('/savings/isa/rate')
    @login_required
    def isa_rate():
        try:
            goals.interest_rate(request.form.get('account',''),request.form.get('rate',''),request.form.get('date',''))
            flash('Cash ISA annual interest rate updated privately. Recorded interest credits are unchanged.')
        except (ValueError,TypeError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'Interest rate could not be saved.')
        return redirect(url_for('savings_goals_page'))

    @app.post('/savings/isa/balance')
    @login_required
    def isa_balance():
        try:
            from finance import wealth_history
            key=request.form.get('account','')
            account=goals.load()['accounts'].get(key)
            if not account or account['type'] not in goals.ISA: raise ValueError('Choose an existing adult ISA.')
            wealth_history.record(account['name'],account['kind'],request.form.get('date',''),request.form.get('balance',''),today=goals.today())
            flash('Dated ISA balance saved. Interest and payments are separate records; they do not automatically change this valuation.')
        except (ValueError,TypeError,OSError) as error: flash(str(error) if isinstance(error,ValueError) else 'Balance could not be saved.')
        return redirect(url_for('savings_goals_page'))

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
