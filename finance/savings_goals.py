"""Private savings targets and dated ISA subscriptions, separate from valuations."""
import calendar
import fcntl
import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from zoneinfo import ZoneInfo
from finance.wealth_history import amount
from storage import write_json

FILE = Path(__file__).resolve().parents[1] / 'data' / 'savings_goals.json'
TYPES = {'savings':'Savings goal','premium_bonds':'Premium Bonds','cash_isa':'Adult cash ISA',
         'stocks_isa':'Adult stocks & shares ISA','other_isa':'Other adult ISA (shared allowance only)','junior_isa':'Junior ISA (child allowance not calculated)'}
EVENTS = {'contribution':'New ISA contribution','transfer':'Provider ISA transfer',
          'withdrawal':'Withdrawal','replacement':'Provider-confirmed flexible ISA replacement'}
ISA = {'cash_isa','stocks_isa','other_isa'}


def today(): return datetime.now(ZoneInfo('Europe/London')).date()


def tax_year(on): return on.year if (on.month,on.day) >= (4,6) else on.year-1


def identity(name,kind): return hashlib.sha256((kind+'|'+name.casefold().strip()).encode()).hexdigest()[:24]


def infer(name,kind):
    if 'premium bond' in name.casefold(): return 'premium_bonds'
    if re.search(r'\bisa\b',name,re.I):
        if re.search(r'junior',name,re.I): return 'junior_isa'
        if re.search(r'lifetime|innovative|help to buy',name,re.I): return 'other_isa'
        return 'stocks_isa' if kind == 'investment' else 'cash_isa'
    return 'savings'


def validate(value):
    if not isinstance(value,dict) or not isinstance(value.get('accounts'),dict) or not isinstance(value.get('entries'),list) or not isinstance(value.get('years'),dict):
        raise ValueError('Invalid savings goals file; restore it before editing.')
    if len(value['accounts'])>500 or len(value['years'])>101: raise ValueError('Savings record limit reached.')
    for key,row in value['accounts'].items():
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not 1 <= len(row['name']) <= 90 or any(ord(c)<32 for c in row['name']) or row.get('kind') not in {'savings','investment'} or key != identity(row['name'],row['kind']) or row.get('type') not in TYPES:
            raise ValueError('Invalid savings account settings.')
        if row.get('target') is not None: amount(row['target'])
    identifiers=set()
    if len(value['entries']) > 10000: raise ValueError('Contribution ledger limit reached.')
    for row in value['entries']:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or row['id'] in identifiers or row.get('account') not in value['accounts'] or row.get('event') not in EVENTS or row.get('isa_type',value['accounts'][row.get('account', '')]['type']) not in ISA:
            raise ValueError('Invalid ISA contribution record.')
        identifiers.add(row['id']);date.fromisoformat(row['date'])
        if amount(row['amount']) <= 0: raise ValueError('Enter a positive contribution amount.')
    for year,row in value['years'].items():
        if not re.fullmatch(r'\d{4}',str(year)) or not 2000 <= int(year) <= 2100 or not isinstance(row,dict) or type(row.get('complete',False)) is not bool:
            raise ValueError('Invalid tax-year preferences.')
        if row.get('first_payment'):
            first=date.fromisoformat(row['first_payment'])
            if not date(int(year),4,6)<=first<=date(int(year)+1,4,5): raise ValueError('Choose a payment date within this tax year.')
        for key in ('allowance','cash_limit'):
            if row.get(key) is not None and amount(row[key]) <= 0: raise ValueError('Enter a positive limit.')
        if row.get('allowance') is not None and row.get('cash_limit') is not None and amount(row['cash_limit'])>amount(row['allowance']):
            raise ValueError('Cash limit cannot exceed the shared allowance.')


def load():
    if not FILE.exists(): return {'accounts':{},'entries':[],'years':{}}
    try: value=json.loads(FILE.read_text());validate(value)
    except (OSError,ValueError,TypeError,KeyError): raise ValueError('Savings goals could not be read; restore the private file.') from None
    return value


@contextmanager
def edit():
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        value=load();yield value;validate(value);write_json(FILE,value)


def account_settings(name,kind,account_type,target=None):
    name=name.strip()
    if not name or len(name)>90 or any(ord(c)<32 for c in name) or kind not in {'savings','investment'} or account_type not in TYPES:
        raise ValueError('Choose a valid account and type.')
    target=amount(target) if target not in (None,'') else None
    if target is not None and target <= 0: raise ValueError('Goal must be positive.')
    with edit() as value:
        key=identity(name,kind)
        old=value['accounts'].get(key,{})
        value['accounts'][key]={'name':name,'kind':kind,'type':account_type,'target':str(target) if target is not None else None}
        if old.get('type') != account_type:
            for row in value['years'].values(): row['complete']=False


def record(account,on,value,event='contribution',entry_id=None):
    on=date.fromisoformat(str(on));value=amount(value)
    if on>today() or on.year<2000 or value<=0 or event not in EVENTS: raise ValueError('Use a positive amount and a date no later than today.')
    with edit() as state:
        if account not in state['accounts'] or state['accounts'][account]['type'] not in ISA:
            raise ValueError('Configure this account as an adult ISA first.')
        existing=next((row for row in state['entries'] if row['id']==entry_id),None) if entry_id else None
        if entry_id and not existing: raise ValueError('Contribution not found.')
        if existing: state['years'].setdefault(str(tax_year(date.fromisoformat(existing['date']))),{})['complete']=False
        row={'id':entry_id or uuid.uuid4().hex,'account':account,'date':on.isoformat(),'amount':str(value),'event':event,'isa_type':state['accounts'][account]['type']}
        if existing: state['entries'][state['entries'].index(existing)]=row
        else: state['entries'].append(row)
        state['years'].setdefault(str(tax_year(on)),{})['complete']=False


def remove(entry_id):
    with edit() as state:
        row=next((r for r in state['entries'] if r['id']==entry_id),None)
        if not row: raise ValueError('Contribution not found.')
        state['entries'].remove(row)
        state['years'].setdefault(str(tax_year(date.fromisoformat(row['date']))),{})['complete']=False


def year_settings(year,allowance,cash_limit,complete,first_payment=None):
    year=int(year)
    if not 2000<=year<=tax_year(today())+1: raise ValueError('Choose a valid tax year.')
    allowance=amount(allowance) if allowance not in ('',None) else None
    cash_limit=amount(cash_limit) if cash_limit not in ('',None) else None
    if allowance is not None and allowance<=0 or cash_limit is not None and cash_limit<=0: raise ValueError('Use positive limits.')
    if cash_limit is not None and allowance is not None and cash_limit>allowance: raise ValueError('Cash limit cannot exceed the overall allowance.')
    first_payment=date.fromisoformat(first_payment).isoformat() if first_payment else None
    if first_payment and not date(year,4,6)<=date.fromisoformat(first_payment)<=date(year+1,4,5): raise ValueError('Choose a payment date within this tax year.')
    with edit() as state:
        state['years'][str(year)]={'allowance':str(allowance) if allowance is not None else None,
                                  'cash_limit':str(cash_limit) if cash_limit is not None else None,'complete':bool(complete),'first_payment':first_payment}


def bar(value,limit):
    if value is None or limit is None or limit<=0: return {'percent':None,'remaining':None,'over':None}
    return {'percent':min(Decimal(100),max(Decimal(0),value/limit*100)),
            'remaining':max(Decimal(0),limit-value),'over':max(Decimal(0),value-limit)}


def monthly_plan(remaining,year,on,first_payment=None):
    """Monthly payment opportunities; keep the original day through short months."""
    start,end=date(year,4,6),date(year+1,4,5)
    anchor=date.fromisoformat(first_payment) if first_payment else max(start,on)
    dates=[]
    for offset in range(13):
        month_index=anchor.year*12+anchor.month-1+offset
        y,m=divmod(month_index,12);m+=1
        payment=date(y,m,min(anchor.day,calendar.monthrange(y,m)[1]))
        if payment>end: break
        if payment>=max(start,on): dates.append(payment)
    result={'anchor':anchor,'dates':dates,'count':len(dates),'deadline':end,'amount':None,'final_amount':None,
            'status':'Tax year ended' if on>end else 'Enter the applicable allowance' if remaining is None else 'No monthly payments before the deadline' if not dates else 'Allowance already used' if remaining==0 else 'Monthly target'}
    if remaining is not None and dates:
        # Distribute whole pennies evenly; the last payment absorbs the remainder.
        pennies=int(remaining*100)
        regular=(remaining/len(dates)).quantize(Decimal('0.01'),rounding=ROUND_CEILING)
        amounts=[];left=Decimal(pennies)/100
        for index in range(len(dates)):
            value=left if index==len(dates)-1 else min(regular,left)
            amounts.append(value);left-=value
        result.update(amount=regular,final_amount=amounts[-1],payments=list(zip(dates,amounts)))
    return result


def review(wealth=None,year=None,state=None,on=None,bond_balances=None):
    on=on or today();year=int(year if year is not None else tax_year(on))
    if not 2000<=year<=tax_year(on)+1: raise ValueError('Choose a valid tax year.')
    state=state if state is not None else load();validate(state)
    accounts={key:{**row,'id':key,'balance':None,'balance_date':None} for key,row in state['accounts'].items()}
    for row in (wealth or {}).get('accounts',[]):
        key=identity(row['name'],row['kind']); config=state['accounts'].get(key,{})
        accounts[key]={**row,**config,'id':key,'name':row['name'],'kind':row['kind'],
                       'type':config.get('type',infer(row['name'],row['kind'])),'target':config.get('target'),
                       'balance_date':row['latest']['date']}
    if bond_balances is None:
        from finance.premium_bonds import load as load_bonds
        try: bond_balances=load_bonds()['balances']
        except ValueError: bond_balances=[]
    bonds=[r for r in bond_balances if r['date']<=on.isoformat()]
    existing=[row for row in accounts.values() if row['type']=='premium_bonds']
    if bonds:
        last=max(bonds,key=lambda r:r['date'])
        if not existing:
            key=identity('Premium Bonds','savings')
            accounts[key]={'id':key,'name':'Premium Bonds','kind':'savings','type':'premium_bonds','target':None,
                           'balance':amount(last['amount']),'balance_date':last['date']}
        elif len(existing)==1 and (existing[0].get('latest',{}).get('source') != 'manual' or last['date']>str(existing[0]['balance_date'])):
            existing[0].update(balance=amount(last['amount']),balance_date=last['date'])
    config=state['years'].get(str(year),{})
    allowance=amount(config['allowance']) if config.get('allowance') is not None else (Decimal(20000) if 2024<=year<=2027 and 'allowance' not in config else None)
    cash_limit=amount(config['cash_limit']) if config.get('cash_limit') is not None else (Decimal(20000) if 2024<=year<=2026 and 'cash_limit' not in config else None)
    entries=[row for row in state['entries'] if tax_year(date.fromisoformat(row['date']))==year and row['date']<=on.isoformat()]
    used=sum((amount(e['amount']) for e in entries if e['event']=='contribution'),Decimal(0))
    cash_used=sum((amount(e['amount']) for e in entries if e['event']=='contribution' and e.get('isa_type',state['accounts'][e['account']]['type'])=='cash_isa'),Decimal(0))
    for key,row in accounts.items():
        row['contributions']=sum((amount(e['amount']) for e in entries if e['account']==key and e['event']=='contribution'),Decimal(0))
        if row['type'] in ISA:
            row.update(bar(row['contributions'],allowance));row['limit']=allowance
        else:
            row['limit']=Decimal(50000) if row['type']=='premium_bonds' else amount(row['target']) if row.get('target') else None
            row.update(bar(row.get('balance'),row['limit']))
        row['entries']=sorted([dict(e,event_label=EVENTS[e['event']]) for e in entries if e['account']==key],key=lambda e:e['date'],reverse=True)
    shared={'used':used,'limit':allowance,**bar(used,allowance),'complete':config.get('complete',False)}
    cash={'used':cash_used,'limit':cash_limit,**bar(cash_used,cash_limit)}
    pb=[row for row in accounts.values() if row['type']=='premium_bonds']
    pb_total=sum((row['balance'] for row in pb),Decimal(0)) if pb and all(row.get('balance') is not None for row in pb) else None
    years=sorted({tax_year(on),tax_year(on)-1,tax_year(on)-2,year,*[tax_year(date.fromisoformat(e['date'])) for e in state['entries']]},reverse=True)
    return {'accounts':list(accounts.values()),'year':year,'label':f'{year}/{str(year+1)[2:]}','start':date(year,4,6),'end':date(year+1,4,5),
            'shared':shared,'cash':cash,'monthly':monthly_plan(shared['remaining'],year,on,config.get('first_payment')),'premium':{'balance':pb_total,'limit':Decimal(50000),**bar(pb_total,Decimal(50000))},
            'years':years,'has_isa':bool(entries) or any(row['type'] in ISA for row in accounts.values()),'has_cash':cash_used>0 or any(row['type']=='cash_isa' for row in accounts.values()),'today':on}


def receipt_lines(view):
    from textwrap import wrap
    lines=[]
    if view['premium']['balance'] is not None:
        row=view['premium'];lines+=['PREMIUM BONDS HOLDING GOAL',f"GBP {row['balance']:.2f} / 50000.00",f"{row['percent']:.0f}% FULL / GBP {row['remaining']:.2f} SPACE"]
        if row['over']: lines.append('RECORDED HOLDINGS EXCEED LIMIT')
    for row in view['accounts']:
        if row['type']=='savings' and row['limit'] and row['balance'] is not None:
            lines += [row['name'].upper()+' GOAL',f"GBP {row['balance']:.2f} / {row['limit']:.2f} ({row['percent']:.0f}%)"]
    if view['has_isa']:
        row=view['shared'];lines += ['ISA NEW CONTRIBUTIONS '+view['label'],f"RECORDED GBP {row['used']:.2f}"]
        if row['limit'] is not None: lines.append(f"SHARED ALLOWANCE GBP {row['limit']:.2f}")
        for account in view['accounts']:
            if account['type'] in ISA: lines.append(f"{account['name']}: GBP {account['contributions']:.2f}")
        if row['complete'] and row['remaining'] is not None: lines.append(f"RECORDED SPACE GBP {row['remaining']:.2f}")
        else: lines.append('RECORDS MAY BE INCOMPLETE')
        plan=view['monthly']
        if plan['amount'] is not None:
            lines += [f"ISA MONTHLY TARGET GBP {plan['amount']:.2f}",f"{plan['count']} PAYMENTS BY {plan['deadline']}",f"FINAL PAYMENT GBP {plan['final_amount']:.2f}"]
            if not row['complete']: lines.append('ESTIMATE FROM RECORDED CONTRIBUTIONS')
        else: lines.append(plan['status'].upper())
        if row['over']: lines.append('RECORDED CONTRIBUTIONS EXCEED LIMIT')
        if view['has_cash'] and view['cash']['limit'] is None: lines.append('VERIFY CASH ISA LIMIT FOR THIS YEAR')
    return [part for line in lines for part in wrap(line,width=40)]
