"""Private property records, dated valuations and shared mortgage references."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
from urllib.parse import urlsplit
from finance.money import parse, ZERO
from storage import PrivateStore
from receipt.local_time import uk_today

FILE = Path(__file__).resolve().parents[1] / 'data' / 'assets.json'
DEFAULT = {'schema_version':1, 'properties':[], 'mortgages':[]}


def validate(value):
    if not isinstance(value,dict) or value.get('schema_version',1)!=1: raise ValueError('Unsupported asset records')
    ids=set(); names=set()
    for kind in ('properties','mortgages'):
        rows=value.get(kind)
        if not isinstance(rows,list) or len(rows)>100: raise ValueError('Too many asset records')
        for row in rows:
            if not isinstance(row,dict) or not re.fullmatch(r'[a-f0-9]{12}',row.get('id','')) or row['id'] in ids: raise ValueError('Invalid asset identifier')
            ids.add(row['id'])
            name=row.get('name','')
            if not isinstance(name,str) or not name.strip() or len(name)>90 or any(ord(c)<32 for c in name): raise ValueError('Enter a short label')
            if kind=='mortgages':
                if name.casefold() in names or name.casefold() in ('amex','american express'): raise ValueError('Mortgage names must be unique and distinct from cards')
                names.add(name.casefold())
                amount=parse(row.get('balance'))
                if amount is None or not ZERO<=amount<=100000000: raise ValueError('Enter your outstanding mortgage liability')
                on=date.fromisoformat(row.get('date',''))
                if on>uk_today(): raise ValueError('Mortgage balance date cannot be in the future')
            else:
                if not isinstance(row.get('address',''),str) or len(row.get('address',''))>300: raise ValueError('Invalid private address')
                share=parse(row.get('share'))
                if share is None or not 0<share<=100: raise ValueError('Ownership share must be above 0 and at most 100 percent')
                url=row.get('url','')
                if url and (urlsplit(url).scheme!='https' or urlsplit(url).hostname not in ('www.zoopla.co.uk','zoopla.co.uk') or urlsplit(url).username): raise ValueError('Use an HTTPS Zoopla property link')
                history=row.get('valuations',[])
                if not isinstance(history,list) or len(history)>240: raise ValueError('Too many valuations')
                dates=set()
                for point in history:
                    on=date.fromisoformat(point.get('date',''))
                    amount=parse(point.get('value'))
                    if on>uk_today() or on in dates or amount is None or not ZERO<=amount<=100000000: raise ValueError('Enter a non-negative dated valuation, no later than today')
                    dates.add(on)
                    low=parse(point.get('low')) if point.get('low') not in ('',None) else amount
                    high=parse(point.get('high')) if point.get('high') not in ('',None) else amount
                    if low is None or high is None or not ZERO<=low<=amount<=high<=100000000: raise ValueError('Valuation must sit within its estimated range')
                    if point.get('source') not in ('Manual','Zoopla estimate','Agent valuation','Surveyor valuation'): raise ValueError('Choose a valuation source')
    linked=set(); mortgage_ids={row['id'] for row in value['mortgages']}
    for row in value['properties']:
        mortgage=row.get('mortgage','')
        if mortgage and (mortgage not in mortgage_ids or mortgage in linked): raise ValueError('Link a mortgage to only one property; split liabilities explicitly for multiple properties')
        if mortgage: linked.add(mortgage)


def store(): return PrivateStore(FILE,default=lambda:deepcopy(DEFAULT),validate=validate,schema_version=1,migrations={0:lambda value:value})
def load(): return store().read()


def merged_debts(existing,state=None):
    state=load() if state is None else state
    names={row['name'].casefold() for row in state['mortgages']}
    # A same-named legacy mortgage becomes the one canonical record here.
    for row in existing:
        if str(row.get('name','')).casefold() in names and row.get('type')!='mortgage':
            raise ValueError('A property mortgage name conflicts with a different debt')
    legacy={str(row.get('name','')).casefold():row for row in existing}
    return [row for row in existing if str(row.get('name','')).casefold() not in names]+[
        {**legacy.get(row['name'].casefold(),{}),'name':row['name'],'balance':row['balance'],'type':'mortgage','asset_mortgage_id':row['id'],'balance_date':row['date']} for row in state['mortgages']]


def property_review(state=None,today=None):
    state=load() if state is None else state;validate(state);today=today or uk_today()
    mortgages={row['id']:row for row in state['mortgages']};rows=[]
    for item in state['properties']:
        history=sorted(item['valuations'],key=lambda p:p['date'])
        latest=history[-1] if history else None;debt=mortgages.get(item.get('mortgage'))
        amount=parse(latest['value']) if latest else None
        owned=amount*parse(item['share'])/100 if amount is not None else None
        liability=parse(debt['balance']) if debt else ZERO
        age=(today-date.fromisoformat(latest['date'])).days if latest else None
        rows.append({**item,'history':history,'latest':latest,'owned':owned,'liability':liability,
                     'equity':owned-liability if owned is not None else None,'age':age,'stale':age is None or age>90,
                     'mortgage_record':debt,'mortgage_stale':bool(debt and (today-date.fromisoformat(debt['date'])).days>90),
                     'change':amount-parse(history[0]['value']) if len(history)>1 else None})
    return {'properties':rows,'mortgages':list(mortgages.values()),'owned_value':sum((r['owned'] for r in rows if r['owned'] is not None),ZERO),
            'equity':sum((r['equity'] for r in rows if r['equity'] is not None),ZERO),'missing':any(r['owned'] is None for r in rows),'stale':any(r['stale'] or r['mortgage_stale'] for r in rows)}


def net_worth(cash,savings,investments,debts,settings,today=None,state=None):
    view=property_review(state,today)
    debt_total=sum((parse(row['balance'],ZERO) for row in debts),ZERO)
    physical=parse(settings.get('physical_cash_held'),ZERO)
    values={'Bank cash':parse(cash),'Physical cash (manual)':physical,'Recorded savings':parse(savings),
            'Recorded investments':parse(investments),'Property ownership share':view['owned_value']}
    known=sum((v for v in values.values() if v is not None),ZERO)
    return {**view,'components':values,'debts':debts,'debt_total':debt_total,'known_total':known-debt_total,
            'complete':all(v is not None for v in values.values()) and not view['missing'],
            'note':'Known recorded assets minus known debts; confirm coverage and account overlap. Property equity is not spendable cash.'}
