"""Private hypothetical purchases, savings priorities and frozen monthly reviews."""
import fcntl
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from finance.projection import money, day, format_runway
from storage import write_json

FILE = Path(__file__).resolve().parents[1]/'data'/'finance_planning.json'


def validate(value):
    if isinstance(value, dict) and value.get('schema_version', 1) != 1: raise ValueError('Unsupported planning version')
    if not isinstance(value,dict): raise ValueError('Invalid planning data')
    for field in ('purchases','priorities'):
        rows=value.get(field,[])
        if not isinstance(rows,list) or len(rows)>100: raise ValueError('Too many plans')
        ids=set()
        for row in rows:
            if not isinstance(row,dict) or not re.fullmatch(r'[a-f0-9]{12}',row.get('id','')) or row['id'] in ids: raise ValueError('Invalid plan')
            ids.add(row['id'])
            if not isinstance(row.get('name'),str) or not row['name'].strip() or len(row['name'])>120: raise ValueError('Enter a name up to 120 characters')
            if money(row.get('amount')) is None or money(row['amount'])<0 or money(row['amount'])>10000000: raise ValueError('Enter a valid positive amount')
            if field=='purchases' and (not day(row.get('date')) or type(row.get('enabled')) is not bool): raise ValueError('Enter a purchase date')
            if field=='priorities' and (row.get('kind') not in {'cash','premium','isa','other'} or type(row.get('priority')) is not int or not 1<=row['priority']<=100): raise ValueError('Invalid savings priority')
    if 'cashflow' in value:
        from finance.cash_scenarios import validate as validate_scenario
        validate_scenario(value['cashflow'])
    reviews=value.get('reviews',{})
    if not isinstance(reviews,dict) or len(reviews)>60: raise ValueError('Invalid monthly reviews')
    from web_control.finance_insights import validate as validate_snapshots
    for month,row in reviews.items():
        if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month) or not isinstance(row,dict) or not isinstance(row.get('snapshot'),dict) or row['snapshot'].get('month')!=month: raise ValueError('Invalid reviewed month')
        try:
            datetime.fromisoformat(row['reviewed_at'])
            validate_snapshots([row['snapshot']])
        except (KeyError,TypeError,ValueError): raise ValueError('Invalid reviewed snapshot') from None


def store():
    from storage import PrivateStore
    return PrivateStore(FILE,default=lambda:{'purchases':[],'priorities':[],'reviews':{}},validate=validate, schema_version=1, migrations={0: lambda value: value})


def load():
    value=store().read()
    return {'purchases':[],'priorities':[],'reviews':{},**value}


def update(change):
    store().update(change)


def scenario(projection,purchases,today):
    active=[p for p in purchases if p['enabled'] and day(p['date'])>=today]
    if not projection['valid']: return {'valid':False,'active':active}
    cash=projection['cash']-projection['buffer']; runout=None
    dated={}
    for event in projection['events']:
        dated[event['date']]=dated.get(event['date'],Decimal(0))+event['amount']
    for purchase in active:
        on=day(purchase['date']);dated[on]=dated.get(on,Decimal(0))+money(purchase['amount'])
    points=[]
    for offset in range(projection['horizon']+1):
        on=today+timedelta(days=offset)
        cash-=dated.get(on,Decimal(0))+(projection.get('daily_cost',projection['daily']) if offset else 0)
        if cash<0 and runout is None: runout=offset
        if offset<=30:points.append({'date':on,'cash':cash})
    return {'valid':True,'active':active,'days':runout,'duration':format_runway(runout,today) if runout is not None else None,
            'date':today+timedelta(days=runout) if runout is not None else None,'points':points,
            'total':sum((money(p['amount']) for p in active),Decimal(0)),
            'outside':sum(day(p['date'])>projection['horizon_end_date'] for p in active),
            'baseline_days':projection.get('cash_days'),'baseline_duration':projection.get('cash_duration')}


def allocation(plan,priorities,goals,purchases,today):
    budget=next((b['amount'] for b in plan.get('buckets',[]) if b['name']=='Savings contribution'),None)
    if budget is None:return {'available':None,'rows':[]}
    # Optional purchases are hypothetical and only reduce the planning recommendation.
    cost=sum((money(p['amount']) for p in purchases if p['enabled'] and today<=day(p['date'])<=plan['end']),Decimal(0))
    extra=next((b['amount'] for b in plan.get('buckets',[]) if b['name']=='Additional spending money'),Decimal(0))
    reduction=max(Decimal(0),cost-extra)
    budget=max(Decimal(0),budget-reduction);left=budget;rows=[]
    isa=(goals or {}).get('shared',{}).get('remaining');premium=(goals or {}).get('premium',{}).get('remaining')
    for row in sorted(priorities,key=lambda r:(r['priority'],r['name'].casefold())):
        wanted=money(row['amount']);limit=isa if row['kind']=='isa' else premium if row['kind']=='premium' else wanted
        capped=min(wanted,limit) if limit is not None else Decimal(0)
        amount=min(left,capped);left-=amount
        if row['kind']=='isa' and isa is not None:isa-=amount
        if row['kind']=='premium' and premium is not None:premium-=amount
        rows.append({**row,'allocated':amount,'gap':wanted-amount,'percent':float(amount/wanted*100) if wanted else 0,'limit_unknown':limit is None})
    return {'available':budget,'rows':rows,'unallocated':left,'purchase_cost':cost,'savings_reduction':reduction}


def reminders(projection,monthly,yearly,settings,today,notice=60):
    from finance.yearly_subscriptions import next_renewal
    rows=[];seen=set()
    for item in yearly:
        due=next_renewal(item,today)
        if due and 0<=(due-today).days<=notice:
            rows.append({'name':item.get('name','Subscription'),'date':due,'kind':'Annual renewal','days':(due-today).days})
    for item in monthly+settings.get('commitments',[]):
        due=day(item.get('end_date'))
        key=(item.get('name','Commitment'),due)
        if due and 0<=(due-today).days<=notice and key not in seen:
            seen.add(key);rows.append({'name':key[0],'date':due,'kind':'Contract ending','days':(due-today).days})
    return sorted(rows,key=lambda r:(r['date'],r['name']))
