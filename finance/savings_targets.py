"""Read-only account snapshots and non-overlapping hypothetical goal allocation."""
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from copy import deepcopy
import re
from finance.projection import money

ZERO=Decimal(0)
CENT=Decimal('0.01')


def load_view(today):
    from finance.wealth_history import review
    from finance.savings_goals import review as goals_review, identity
    from savings_runway import load_savings
    from finance.investments import load_investments
    root=Path(__file__).resolve().parents[1]
    wealth=review(today)
    known={identity(row['name'],row['kind']) for row in wealth['accounts']}
    for kind,data in [('savings',load_savings(root/'data'/'savings.json')),('investment',load_investments())]:
        for row in data.get('accounts',[]):
            if not isinstance(row,dict) or not row.get('name'): continue
            key=identity(row['name'],kind)
            balance=money(row.get('balance'))
            if key in known or balance is None or balance<0: continue
            wealth['accounts'].append(dict(row,kind=kind,balance=balance,latest={'date':data.get('updated') or ''}))
            known.add(key)
    view=goals_review(wealth,on=today)
    rows=[]
    for account in view['accounts']:
        target=money(account.get('target'))
        if target is None and account['type']=='premium_bonds': target=Decimal(50000)
        rows.append({'id':account['id'],'name':account['name'],'kind':account['kind'],'type':account['type'],
            'balance':money(account.get('balance')),'date':account.get('balance_date'), 'target':target,
            'share':money(account.get('monthly_share'),ZERO),
            'isa_contributions':account.get('contributions',ZERO) if account['type'] in {'cash_isa','stocks_isa','other_isa'} else None})
    return rows


def link_regular_savings(events, accounts):
    """Link regular savings to one account; ambiguous destinations stay unlinked."""
    def key(value): return re.sub(r'[^a-z0-9]', '', str(value).casefold())
    def hl(value):
        original=str(value)
        value=key(value)
        return 'hargreaves' in value or value.startswith(('hlam','handl')) or value=='hl' or value.startswith('hlisa') or bool(re.search(r'\bh\s*(?:&|and)\s*l\b|\bhl\b',original,re.I))
    for event in events:
        if event.get('amount',ZERO)<=0: continue
        candidates=[row for row in accounts if key(row['name'])==key(event['name']) or (hl(row['name']) and hl(event['name']))]
        if len(candidates)==1 and (event.get('category')=='savings' or hl(event['name'])):
            event['savings_account']=candidates[0]['id']


def allocate(accounts, periods, automatic_events=()):
    rows=deepcopy(accounts)
    for row in rows:
        row.update(projected=row['balance'],added=ZERO,first=ZERO,automatic_added=ZERO,first_automatic=ZERO,goal_date=None)
        if row['target'] and row['balance'] is not None and row['balance']>=row['target']: row['goal_date']='already'
    explicit=any(row['share']>0 for row in rows)
    fraction=min(Decimal(100),sum((row['share'] for row in rows if row['balance'] is not None and row['target']),ZERO))/100 if explicit else Decimal(1)
    unallocated=ZERO
    timeline=[(period['date'],1,index,period) for index,period in enumerate(periods)]
    timeline += [(event['date'],0,None,event) for event in automatic_events if event.get('savings_account')]
    for on,kind,index,period in sorted(timeline,key=lambda item:(item[0],item[1])):
        if kind==0:
            row=next((r for r in rows if r['id']==period['savings_account']),None)
            if row is None or row['projected'] is None: continue
            part=period['amount']
            row['projected']+=part;row['added']+=part;row['automatic_added']+=part
            if periods and periods[0]['date']<=on<=periods[0]['end']: row['first_automatic']+=part
            if row['target'] and row['projected']>=row['target'] and row['goal_date'] is None and period.get('funded',True): row['goal_date']=on
            continue
        amount=period['savings']
        remaining=(amount*fraction).quantize(CENT,rounding=ROUND_DOWN)
        assigned=ZERO
        while remaining>=CENT:
            eligible=[row for row in rows if row['projected'] is not None and row['target'] and row['projected']<row['target'] and (not explicit or row['share']>0)]
            if not eligible: break
            weights=sum((row['share'] if explicit else Decimal(1) for row in eligible),ZERO)
            available=remaining; progressed=ZERO
            for row in eligible:
                part=(available*(row['share'] if explicit else Decimal(1))/weights).quantize(CENT,rounding=ROUND_DOWN)
                part=min(part,row['target']-row['projected'])
                if not part and remaining>=CENT: part=min(CENT,row['target']-row['projected'])
                part=min(part,remaining)
                row['projected']+=part;row['added']+=part
                if index==0:row['first']+=part
                remaining-=part;assigned+=part;progressed+=part
                if row['projected']>=row['target'] and row['goal_date'] is None: row['goal_date']=period['date'] if period.get('funded',True) else None
            if progressed==0:break
        unallocated+=amount-assigned
    return {'accounts':rows,'unallocated':unallocated,'current_total':sum((row['balance'] for row in rows if row['balance'] is not None),ZERO),
        'projected_total':sum((row['projected'] for row in rows if row['projected'] is not None),ZERO),
        'complete':all(row['balance'] is not None for row in rows)}
