"""Private review of uncertain payments; category edits never verify a bill payment."""
import fcntl
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from flask import abort, flash, redirect, render_template, request, url_for
from finance_trends import DEFAULT_CATEGORIES, _amount, _parse_date, categorise_transaction, load_rules
from storage import write_json
from web_control.payments import external_payments,payment_identity

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / 'data' / 'finance_review_queue.json'
RULES = ROOT / 'data' / 'finance_categories.json'


def read(path):
    try: value = json.loads(path.read_text())
    except FileNotFoundError: return {}
    except (OSError,ValueError): raise ValueError('Saved finance review data could not be read.') from None
    if not isinstance(value, dict): raise ValueError('Invalid finance review data.')
    if path == QUEUE:
        if not isinstance(value.get('payments', []),list) or not isinstance(value.get('unmatched', []),list) or not isinstance(value.get('reviewable',[]),list):
            raise ValueError('Invalid saved payment review.')
        for row in value.get('payments', [])+value.get('reviewable',[]):
            if not isinstance(row,dict) or not all(isinstance(row.get(key),str) for key in ('id','date','merchant')):
                raise ValueError('Invalid saved payment review.')
            from datetime import date
            date.fromisoformat(row['date'])
            if not isinstance(row.get('amount'),(int,float)) or not math.isfinite(row['amount']) or row['amount'] <= 0:
                raise ValueError('Invalid saved payment amount.')
    if path == RULES and (not isinstance(value.get('transactions', []),list) or any(not isinstance(row,dict) for row in value.get('transactions', []))):
        raise ValueError('Invalid saved transaction rules.')
    return value


def save_review(transactions, rows, today):
    rules = load_rules(RULES); payments = []; reviewable=[]
    for tx in external_payments(transactions):
        paid = _parse_date(tx)
        if not paid or not 0 <= (today-paid).days <= 29: continue
        merchant = str(tx.get('merchant_name') or tx.get('merchant') or tx.get('description') or '').strip()[:160]
        if not merchant: continue
        amount = round(_amount(tx),2)
        if not math.isfinite(amount) or amount <= 0: continue
        identity=payment_identity(paid,merchant,amount)
        item=dict(id=identity,date=paid.isoformat(),merchant=merchant,amount=amount)
        reviewable.append(item)
        if categorise_transaction(tx,rules)=='OTHER': payments.append(item)
    unmatched = [dict(name=row['item']['name'],amount=row['item']['amount']) for row in rows if row['transaction'] is None]
    state={'checked_at':datetime.now(timezone.utc).isoformat(),'payments':payments[:300], 'unmatched':unmatched,'reviewable':reviewable[:1000]}
    write_json(QUEUE,state)
    return state


def register(app, login_required):
    @app.get('/finance-reconciliation')
    @login_required
    def finance_reconciliation():
        from receipt.local_time import uk_receipt_time
        try: state = read(QUEUE); rules = load_rules(RULES); error = None
        except ValueError as problem: state, rules, error = {}, {}, str(problem)
        chosen=request.args.get('payment')
        if chosen:
            payments=[row for row in state.get('reviewable',state.get('payments',[])) if row.get('id')==chosen]
            if not payments: abort(404)
        else: payments = [row for row in state.get('payments',[]) if categorise_transaction(
            {'date':row['date'],'description':row['merchant'],'amount':-row['amount']},rules) == 'OTHER']
        return render_template('reconciliation.html',payments=payments,unmatched=state.get('unmatched',[]),
                               categories=DEFAULT_CATEGORIES, checked=uk_receipt_time(state.get('checked_at')), error=error)

    @app.post('/finance-reconciliation/category')
    @login_required
    def finance_category():
        try:
            category = request.form.get('category','')
            if category not in DEFAULT_CATEGORIES or category == 'OTHER': raise ValueError('Choose a category.')
            state = read(QUEUE)
            row = next((row for row in state.get('reviewable',state.get('payments',[])) if row['id'] == request.form.get('id')),None)
            if row is None: abort(404)
            scope = request.form.get('scope','purchase')
            if scope not in {'purchase','merchant'}: raise ValueError('Choose a rule scope.')
            RULES.parent.mkdir(parents=True,exist_ok=True)
            with RULES.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                rules = read(RULES)
                if scope == 'merchant':
                    rules = {row['merchant']:category, **{key:value for key,value in rules.items() if key != row['merchant']}}
                else:
                    entries = rules.get('transactions',[])
                    if not isinstance(entries,list): raise ValueError('Invalid saved transaction rules.')
                    rule = {key:row[key] for key in ('date','merchant','amount')}; rule['category'] = category
                    entries = [entry for entry in entries if not all(entry.get(key) == rule[key] for key in ('date','merchant','amount'))]
                    rules['transactions'] = [rule,*entries]
                write_json(RULES,rules)
            flash('Category rule saved privately. Refresh Finance to recalculate charts and future receipts.')
        except (ValueError,OSError) as problem: flash(str(problem) if isinstance(problem,ValueError) else 'Category rule could not be saved.')
        return redirect(url_for('finance_reconciliation'))
