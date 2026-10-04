"""Authenticated private planning changes; source figures are never accepted from forms."""
from datetime import date, datetime, timezone
import json
import uuid
from flask import abort, flash, redirect, request, url_for
from finance import planning


def register(app,login_required):
    @app.context_processor
    def planning_context():
        from receipt.local_time import uk_receipt_time
        return {'planning_local_time':uk_receipt_time}

    @app.get('/finance/planning')
    @login_required
    def finance_planning_page():
        from flask import render_template
        from web_control import finance_insights
        from zoneinfo import ZoneInfo
        today=datetime.now(ZoneInfo('Europe/London')).date()
        try:
            plans=planning.load()
            from services.subscriptions import load_subscriptions
            from finance.receipt import load_finance_settings
            subscriptions=load_subscriptions()
            reminders=planning.reminders({},subscriptions.get('monthly',[]),subscriptions.get('yearly',[]),load_finance_settings(),today)
            view={'state':plans,'scenario':{'valid':False},'allocation':{'available':None},'reminders':reminders}
        except (ValueError,TypeError,OSError): view={'error':'Private plans could not be read. Restore a valid backup.'}
        try:
            history=json.loads(finance_insights.FILE.read_text());finance_insights.validate(history)
        except (OSError,ValueError,TypeError,KeyError):history=[]
        return render_template('planning.html',planning_view=view,insights={'history':history},checked_at=today)

    @app.post('/finance/planning')
    @login_required
    def save_finance_plan():
        kind=request.form.get('kind');mode=request.form.get('mode','save');identity=request.form.get('id') or uuid.uuid4().hex[:12]
        if kind not in {'purchases','priorities'}:abort(400)
        try:
            row={'id':identity,'name':request.form.get('name','').strip(),'amount':request.form.get('amount','')}
            if kind=='purchases':row.update(date=request.form.get('date'),enabled=request.form.get('enabled')=='on')
            else:row.update(kind=request.form.get('account_kind'),priority=int(request.form.get('priority','1')))
            def change(value):
                rows=[r for r in value.get(kind,[]) if r['id']!=identity]
                value[kind]=rows if mode=='delete' else rows+[row]
            planning.update(change);flash('Private plan saved. Refresh Finance to recalculate.')
        except (ValueError,TypeError,OSError):flash('Enter a valid name, amount, date and priority.')
        return redirect(url_for('finance_planning_page'))

    @app.post('/finance/month-review')
    @login_required
    def close_finance_month():
        from web_control import finance_insights
        from zoneinfo import ZoneInfo
        month=request.form.get('month','')
        if request.form.get('confirmed')!='on':abort(400)
        try:
            rows=json.loads(finance_insights.FILE.read_text());finance_insights.validate(rows)
            row=next(r for r in rows if r['month']==month)
            if month>=datetime.now(ZoneInfo('Europe/London')).strftime('%Y-%m'):raise ValueError('Month has not ended')
            def change(value):
                reviews=value.setdefault('reviews',{})
                reviews[month]={'reviewed_at':datetime.now(timezone.utc).isoformat(),'snapshot':row}
                value['reviews']=dict(sorted(reviews.items())[-60:])
            planning.update(change);flash('Dated monthly review saved privately. Coverage limitations remain recorded.')
        except (OSError,ValueError,StopIteration,TypeError):flash('Choose an ended month with a valid saved observation.')
        return redirect(url_for('finance_planning_page'))
