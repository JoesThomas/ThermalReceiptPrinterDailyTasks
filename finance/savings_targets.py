"""Read-only account snapshots and non-overlapping hypothetical goal allocation."""
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from copy import deepcopy
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


def allocate(accounts, periods):
    rows=deepcopy(accounts)
    for row in rows:
        row.update(projected=row['balance'],added=ZERO,first=ZERO,goal_date=None)
        if row['target'] and row['balance'] is not None and row['balance']>=row['target']: row['goal_date']='already'
    explicit=any(row['share']>0 for row in rows)
    fraction=min(Decimal(100),sum((row['share'] for row in rows if row['balance'] is not None and row['target']),ZERO))/100 if explicit else Decimal(1)
    unallocated=ZERO
    for index,period in enumerate(periods):
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
