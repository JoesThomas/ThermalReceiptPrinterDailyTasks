"""Private bank selection and balance collection, independent of the live pipeline."""
import json
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone
from storage import write_json

ROOT=Path(__file__).resolve().parents[1]
SELECTION=ROOT/'data'/'bank_account_selection.json'
CATALOG=ROOT/'data'/'bank_account_catalog.json'
PROVIDERS=('HSBC','MONZO')


def validate(value):
    if not isinstance(value,dict) or any(p not in PROVIDERS for p in value): raise ValueError('Invalid cash account selection.')
    for ids in value.values():
        if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) or not i or len(i)>200 for i in ids) or len(ids)!=len(set(ids)): raise ValueError('Invalid cash account selection.')


def selection():
    from storage import PrivateStore
    return PrivateStore(SELECTION,default=dict,validate=validate).read()


def catalog():
    try:
        value=json.loads(CATALOG.read_text())
        if not isinstance(value,dict) or not isinstance(value.get('accounts'),list): return {'accounts':[]}
        value['accounts']=[row for row in value['accounts'] if isinstance(row,dict) and row.get('provider') in PROVIDERS and isinstance(row.get('id'),str) and row['id'] and isinstance(row.get('name'),str)]
        return value
    except (ValueError,OSError): return {'accounts':[]}


def choose(value):
    validate(value)
    known=catalog()['accounts']
    allowed={p:{a['id'] for a in known if a['provider']==p} for p in PROVIDERS}
    if not any(value.values()) or any(not set(ids)<=allowed[p] for p,ids in value.items()): raise ValueError('Choose at least one current account from the latest bank check.')
    write_json(SELECTION,value)


def number(value):
    from finance.money import parse
    result=parse(value,rounded=False)
    if result is None: raise ValueError('Balance is unavailable.')
    return result


def first(get,token,resource):
    rows=get(token,'/'+resource).get('results',[])
    if not rows or not rows[0].get('account_id'): raise RuntimeError('No account was returned by the bank connection.')
    result=get(token,f"/{resource}/{rows[0]['account_id']}/balance").get('results',[])
    if not result: raise RuntimeError('No balance was returned by the bank connection.')
    return result[0]


def collect(refresh,initial,get):
    selected=selection();rows=[];result={};tokens={};inventory={};stamp=datetime.now(timezone.utc).isoformat()
    for provider in PROVIDERS:
        token=refresh(provider,initial(provider));tokens[provider]=token
        accounts=get(token,'/accounts').get('results',[]);inventory[provider]=accounts
        for index,account in enumerate(accounts,1):
            identity=account.get('account_id')
            if identity: rows.append({'provider':provider,'id':identity,'name':str(account.get('display_name') or account.get('account_type') or f'Account {index}')[:120]})
    # Keep current choices available even if a selected balance later fails.
    write_json(CATALOG,{'checked_at':stamp,'accounts':rows})
    for provider in PROVIDERS:
        token=tokens[provider];accounts=inventory[provider]
        ids=selected.get(provider)
        if ids is None:
            if not accounts or not accounts[0].get('account_id'): raise RuntimeError('No bank account was returned.')
            ids=[accounts[0]['account_id']]
        if not set(ids)<={a.get('account_id') for a in accounts}: raise RuntimeError('A selected account is missing. Review cash account selection after reconnecting.')
        current=available=Decimal(0);parts=[]
        for identity in ids:
            values=get(token,f'/accounts/{identity}/balance').get('results',[])
            if not values or values[0].get('currency','GBP')!='GBP': raise RuntimeError('A selected GBP cash balance is unavailable.')
            row=values[0];c=number(row.get('current'));a=number(row.get('available',c))
            current+=c;available+=a
            parts.append({'name':next((r['name'] for r in rows if r['id']==identity and r['provider']==provider),'Account'),'available':float(a),'current':float(c)})
        result[provider]={'current':float(current),'available':float(available),'currency':'GBP','accounts':parts,
                          'scope':'Selected accounts' if provider in selected else 'First account (default)','checked_at':stamp}
    # Persist only display names and private selection IDs, never credentials or transaction history.
    token=refresh('AMEX',initial('AMEX'));amex=first(get,token,'cards')
    result['AMEX']={'current':float(number(amex.get('current'))),'available':float(number(amex.get('available',0))),
                    'credit_limit':float(number(amex.get('credit_limit',0))),'currency':amex.get('currency','GBP')}
    return result
