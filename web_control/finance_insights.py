"""Explainable finance views and private aggregate monthly observations."""
import fcntl
import json
from datetime import timedelta, date
from decimal import Decimal
from pathlib import Path
from finance.projection import money
from storage import write_json

FILE=Path(__file__).resolve().parents[1]/'data'/'finance_monthly_snapshots.json'


def validate(rows):
    if not isinstance(rows,list) or len(rows)>60: raise ValueError('Invalid finance snapshots.')
    months=set()
    for row in rows:
        if not isinstance(row,dict): raise ValueError('Invalid finance snapshot.')
        on=date.fromisoformat(row['as_of'])
        if row['month']!=on.strftime('%Y-%m') or row['month'] in months: raise ValueError('Invalid snapshot month.')
        months.add(row['month'])
        if row.get('coverage') not in {'complete','partial','unavailable'} or type(row.get('whole_month')) is not bool: raise ValueError('Invalid snapshot coverage.')
        for field in ('income','spending','savings','investments','card_debt','cash'):
            value=row.get(field)
            if value is not None and (money(value) is None or (field!='cash' and money(value)<0)): raise ValueError('Invalid snapshot amount.')


def snapshots(row):
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        rows=json.loads(FILE.read_text()) if FILE.exists() else []
        validate(rows)
        rows=[r for r in rows if r['month']!=row['month']]+[row]
        rows=sorted(rows,key=lambda r:r['month'])[-60:]
        validate(rows)
        write_json(FILE,rows)
    activity_max=max((max(money(r.get('income'),Decimal(0)),money(r.get('spending'),Decimal(0))) for r in rows),default=Decimal(0))
    maximum=max((money(r.get('savings'),Decimal(0))+money(r.get('investments'),Decimal(0)) for r in rows),default=Decimal(0))
    return [dict(r,income_percent=float(money(r.get('income'),Decimal(0))/activity_max*100) if activity_max else 0,spending_percent=float(money(r.get('spending'),Decimal(0))/activity_max*100) if activity_max else 0,percent=float((money(r.get('savings'),Decimal(0))+money(r.get('investments'),Decimal(0)))/maximum*100) if maximum and r.get('savings') is not None and r.get('investments') is not None else None) for r in rows]


def build(projection,balances,summary,month,income,wealth,goals,today):
    payday=projection.get('payday')
    end=payday-timedelta(days=1) if payday else today+timedelta(days=30)
    events=[e for e in projection['events'] if e['date']<=end]
    # Recompute using the full event list so a distant payday is not truncated at 30 days.
    remaining=projection.get('cash');points=[]
    if projection['valid'] and remaining is not None:
        remaining-=projection['buffer']
        by_date={}
        for event in events: by_date[event['date']]=by_date.get(event['date'],Decimal(0))+event['amount']
        for offset in range((end-today).days+1):
            on=today+timedelta(days=offset)
            cost=by_date.get(on,Decimal(0))+(projection.get('daily_cost',projection['daily']) if offset else 0)
            remaining-=cost
            points.append({'date':on,'cash':remaining,'payments':[e for e in events if e['date']==on]})
    lowest=min(points,key=lambda p:p['cash']) if points else None
    lo=hi=None
    if points:
        lo=min(p['cash'] for p in points);hi=max(p['cash'] for p in points)
        for index,p in enumerate(points):
            p.update(x=round(25+550*index/max(1,len(points)-1),2),y=round(140-115*(p['cash']-lo)/max(Decimal(1),hi-lo),2))
    plan=(goals or {}).get('monthly',{})
    target=plan.get('amount');spare=max(Decimal(0),lowest['cash']) if lowest else None
    planning={'target':target,'spare':spare,'gap':max(Decimal(0),target-spare) if target is not None and spare is not None else None}
    coverage=summary.get('source_coverage',[])
    start=summary.get('requested_from')
    snapshot={'month':today.strftime('%Y-%m'),'as_of':today.isoformat(),'coverage':summary.get('bank_data_status','unavailable'),
              'income':str(income['month_total']),'spending':str(month['total']),
              'savings':str(wealth['savings']) if wealth else None,'investments':str(wealth['investments']) if wealth else None,
              'card_debt':str(max(Decimal(0),money(balances.get('AMEX',{}).get('current')))) if money(balances.get('AMEX',{}).get('current')) is not None else None,
              'whole_month':bool(start and start<=today.replace(day=1).isoformat() and summary.get('bank_data_status')=='complete'),
              'cash':str(projection['cash']) if projection.get('cash') is not None else None}
    try: history=snapshots(snapshot);history_error=None
    except (ValueError,TypeError,OSError): history=[];history_error='Private monthly snapshots could not be updated.'
    accounts=[{'provider':provider,'value':money(balances.get(provider,{}).get('available',balances.get(provider,{}).get('current'))),
               'currency':balances.get(provider,{}).get('currency','GBP')} for provider in ('HSBC','MONZO')]
    growth=[]
    for account in (wealth or {}).get('accounts',[]):
        goal=next((a for a in (goals or {}).get('accounts',[]) if a['name'].casefold()==account['name'].casefold() and a['kind']==account['kind']),{})
        growth.append({**account,'interest':goal.get('interest'),'interest_period':(goals or {}).get('label')})
    return {'lowest':lowest,'end':end,'points':points,'line':' '.join(f"{p['x']},{p['y']}" for p in points),
            'chart_min':lo,'chart_max':hi,'planning':planning,'coverage':coverage,'accounts':accounts,'history':history,'history_error':history_error,'growth':growth,
            'attempted':summary.get('bank_fetch_attempted'),'succeeded':summary.get('bank_fetch_succeeded'),
            'requested_from':start,'requested_to':summary.get('requested_to')}
