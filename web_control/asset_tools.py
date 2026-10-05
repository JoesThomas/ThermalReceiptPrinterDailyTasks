"""Private property editing with shared mortgage references and valuation history."""
import uuid
from flask import abort, flash, redirect, render_template, request, url_for
from finance import assets
from receipt.local_time import uk_today


def register(app,login_required):
    @app.get('/finance/assets')
    @login_required
    def assets_page():
        state=assets.load()
        selected=next((row for row in state['properties'] if row['id']==request.args.get('edit')),None)
        return render_template('assets.html',asset_view=assets.property_review(state),asset_edit=selected,today=uk_today())

    @app.post('/finance/assets')
    @login_required
    def assets_save():
        kind=request.form.get('kind')
        if kind not in ('properties','mortgages'):abort(400)
        identity=request.form.get('id') or uuid.uuid4().hex[:12]
        try:
            def change(state):
                old=next((r for r in state[kind] if r['id']==identity),None)
                if request.form.get('id') and old is None:raise ValueError('Record no longer exists')
                rows=[r for r in state[kind] if r['id']!=identity]
                if request.form.get('action')!='delete':
                    row={'id':identity,'name':request.form.get('name','').strip()}
                    if kind=='mortgages':
                        row.update(balance=request.form.get('balance',''),date=request.form.get('date',''))
                    else:
                        history=list((old or {}).get('valuations',[]))
                        if request.form.get('value','').strip():
                            point={key:request.form.get(key,'').strip() for key in ('value','date','low','high','source')}
                            history=[p for p in history if p['date']!=point['date']]+[point]
                        row.update(address=request.form.get('address','').strip(),share=request.form.get('share',''),mortgage=request.form.get('mortgage',''),url=request.form.get('url','').strip(),valuations=history)
                    rows.append(row)
                state[kind]=rows
                assets.validate(state)
                from finance.receipt import load_finance_settings
                assets.merged_debts(load_finance_settings().get('debts',[]),state)
            assets.store().update(change)
            flash('Private asset record saved. Property values remain separate from cash and runway.')
        except (ValueError,TypeError,OSError) as error:flash(str(error))
        return redirect(url_for('assets_page'))
