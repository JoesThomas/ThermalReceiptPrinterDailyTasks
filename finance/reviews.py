"""Private plan/actual reviews, rental ledger and immutable monthly summaries."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from calendar import monthrange
import hashlib
import re
import uuid
from pathlib import Path
from finance.money import parse, ZERO
from finance.projection import day
from finance_trends import _parse_date
from web_control.payments import external_payments
from receipt.local_time import uk_today
from storage import PrivateStore

FILE=Path(__file__).resolve().parents[1]/'data'/'finance_reviews.json'
DEFAULT={'periods':{},'rent_entries':[],'rent_candidates':[],'summaries':{},'month_observations':{},'latest_summary':None}
KINDS=('rent','operating','repair','interest','capital','tax')


def validate(value):
    if not isinstance(value,dict):raise ValueError('Invalid finance reviews')
    for key in ('periods','summaries','month_observations'):
        rows=value.get(key,{})
        if not isinstance(rows,dict) or len(rows)>60:raise ValueError('Too many financial summaries')
        for identity,row in rows.items():
            if not isinstance(row,dict):raise ValueError('Invalid summary')
            if key=='periods':
                if not day(identity) or not day(row.get('observed_on')):raise ValueError('Invalid salary period')
                if not isinstance(row.get('plan'),list):raise ValueError('Invalid saved allocation')
                for bucket in row['plan']:
                    if not isinstance(bucket.get('name'),str) or parse(bucket.get('amount')) is None or parse(bucket['amount'])<0:raise ValueError('Invalid saved plan')
                savings=parse(row.get('confirmed_savings'))
                if row.get('confirmed_savings') is not None and (savings is None or savings<0):raise ValueError('Invalid confirmed savings')
            elif not re.fullmatch(r'\d{4}-\d{2}',identity) or row.get('month')!=identity:raise ValueError('Invalid monthly summary')
    snapshots=list(value.get('summaries',{}).values())+list(value.get('month_observations',{}).values())
    if value.get('latest_summary') is not None:snapshots.append(value['latest_summary'])
    for row in snapshots:
        if not isinstance(row,dict) or not day(row.get('as_of')) or row.get('month')!=day(row['as_of']).strftime('%Y-%m') or row.get('coverage') not in ('complete','partial','unavailable'):raise ValueError('Invalid dated summary')
        for key in ('income','spending','cash','net_worth'):
            if row.get(key) is not None and (parse(row[key]) is None or key in ('income','spending') and parse(row[key])<0):raise ValueError('Invalid frozen amount')
        assumptions=row.get('assumptions')
        if not isinstance(assumptions,dict) or any(parse(assumptions.get(key)) is None or parse(assumptions[key])<0 for key in ('protected_reserves','daily_spending')):raise ValueError('Invalid frozen assumptions')
        if row.get('scope') is not None:
            from finance.scope import validate as validate_scope
            validate_scope(row['scope'])
    for period in value.get('periods',{}).values():
        observed=period.get('observations',{})
        if not isinstance(observed,dict) or len(observed)>5000:raise ValueError('Too many period observations')
        for key,row in observed.items():
            if not re.fullmatch(r'[a-f0-9]{64}',key) or not isinstance(row,dict) or not day(row.get('date')) or parse(row.get('amount')) is None or parse(row['amount'])<0 or row.get('kind') not in ('bills','everyday'):raise ValueError('Invalid period observation')
        if not day(period.get('comparison_from')) or not day(period.get('end')):raise ValueError('Invalid comparison dates')
        for window in period.get('windows',[]):
            if not isinstance(window,list) or len(window)!=2 or not day(window[0]) or not day(window[1]) or window[0]>window[1]:raise ValueError('Invalid observed window')
        actual=period.get('actual',{})
        for key in ('bills','everyday'):
            if key in actual and (parse(actual[key]) is None or parse(actual[key])<0):raise ValueError('Invalid actual spending')
    for field in ('rent_entries','rent_candidates'):
        rows=value.get(field,[])
        if not isinstance(rows,list) or len(rows)>(3000 if field=='rent_entries' else 300):raise ValueError('Too many rental records')
        ids=set();source_ids=set()
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not re.fullmatch(r'[a-f0-9]{12,64}',row['id']) or row['id'] in ids:raise ValueError('Invalid rental entry')
            ids.add(row['id'])
            on=day(row.get('date'));amount=parse(row.get('amount'))
            if not on or on>uk_today() or amount is None or not ZERO<=amount<=10000000:raise ValueError('Enter a past/current date and non-negative amount')
            if field=='rent_entries':
                if row.get('kind') not in KINDS or not re.fullmatch(r'[a-f0-9]{12}',row.get('property','')) or row.get('source') not in ('Manual','Bank observed'):raise ValueError('Invalid property ledger entry')
                if not isinstance(row.get('label'),str) or len(row['label'])>90 or not isinstance(row.get('note',''),str) or len(row.get('note',''))>180:raise ValueError('Invalid ledger label')
                source=row.get('source_id')
                if source and (source in source_ids or not re.fullmatch(r'[a-f0-9]{64}',source)):raise ValueError('A bank rent payment can only be linked once')
                if source:source_ids.add(source)


def store():return PrivateStore(FILE,default=lambda:deepcopy(DEFAULT),validate=validate)
def load():return store().read()


def observations(transactions,bill_rows):
    result={};groups={};used=set();bill_seen=set();bill_counts={}
    for row in external_payments(transactions):
        on=_parse_date(row)
        if not on:continue
        amount=parse(row.get('spend_amount'),ZERO)
        base=f"{on}|{row.get('merchant_name') or row.get('description','')}|{amount}"
        occurrence=groups.get(base,0);groups[base]=occurrence+1
        identity=row.get('transaction_id') or row.get('id')
        if str(identity).startswith('web-idless-'):identity=None
        token=str(identity) if identity else base+'|'+str(occurrence)
        digest=hashlib.sha256(token.encode()).hexdigest()
        result[digest]={'date':str(on),'amount':str(amount),'kind':'everyday','match':base}
    for index,item in enumerate(bill_rows):
        row=item.get('transaction')
        if not row or not (on:=_parse_date(row)):continue
        bill_id=row.get('transaction_id') or row.get('id') or id(row)
        if bill_id in bill_seen:continue
        bill_seen.add(bill_id)
        amount=abs(parse(row.get('amount'),ZERO))
        base=f"{on}|{row.get('merchant_name') or row.get('description','')}|{amount}"
        identity=row.get('transaction_id') or row.get('id')
        digest=hashlib.sha256(str(identity).encode()).hexdigest() if identity else next((key for key,observed in result.items() if observed['match']==base and key not in used),None)
        if not digest:
            occurrence=bill_counts.get(base,0);bill_counts[base]=occurrence+1
            digest=hashlib.sha256((base+'|bill|'+str(occurrence)).encode()).hexdigest()
        used.add(digest)
        result[digest]={'date':str(on),'amount':str(amount),'kind':'bills','match':base}
    return {key:{field:row[field] for field in ('date','amount','kind')} for key,row in result.items()}


def merged_windows(windows):
    result=[]
    for start,end in sorted(windows):
        if result and day(start)<=day(result[-1][1])+timedelta(days=1):result[-1][1]=max(result[-1][1],end)
        else:result.append([start,end])
    return result


def capture(plan,transactions,bill_rows,income,projection,summary,net_worth,tax,today,month_total):
    latest=plan.get('latest');salary_date=latest.isoformat() if latest else None
    comparison_from=today+timedelta(days=1)
    observed=observations(transactions,bill_rows)
    candidates=[];occurrences={}
    for row in income.get('recent',[]):
        if str(row.get('category','')).upper()!='RENT RECEIVED':continue
        identity=f"{row['date']}|{row['name']}|{row['amount']}"
        occurrence=occurrences.get(identity,0);occurrences[identity]=occurrence+1
        candidates.append({'id':hashlib.sha256(f'{identity}|{occurrence}'.encode()).hexdigest(),'date':str(row['date']),'amount':str(row['amount']),'name':str(row['name'])[:160]})
    latest_summary={'month':today.strftime('%Y-%m'),'as_of':today.isoformat(),'coverage':summary.get('bank_data_status','unavailable'),
                    'window_from':summary.get('requested_from'),'window_to':summary.get('requested_to'),
                    'whole_month':bool(summary.get('bank_data_status')=='complete' and day(summary.get('requested_from')) and day(summary['requested_from'])<=today.replace(day=1) and day(summary.get('requested_to')) and day(summary['requested_to'])>=today and today.day==monthrange(today.year,today.month)[1]),
                    'scope':deepcopy(summary.get('collection_scope')),'income':str(income['month_total']),'spending':str(month_total),
                    'cash':str(projection['cash']) if projection['cash'] is not None else None,
                    'net_worth':str(net_worth['known_total']) if net_worth else None,'net_worth_complete':bool(net_worth and net_worth['complete']),
                    'assumptions':{'protected_reserves':str(projection['buffer']),'daily_spending':str(projection['daily']),
                                   'payday':str(projection['payday']) if projection['payday'] else None,
                                   'rental_tax':str(tax['tax']) if tax else None,'tax_rules':tax['rules']['version'] if tax else None}}
    def change(value):
        value['rent_candidates']=candidates[:300]
        value['latest_summary']=latest_summary
        monthly=value.setdefault('month_observations',{})
        monthly[latest_summary['month']]=deepcopy(latest_summary)
        value['month_observations']=dict(sorted(monthly.items())[-60:])
        if salary_date:
            periods=value.setdefault('periods',{})
            if salary_date not in periods and plan.get('valid'):
                periods[salary_date]={'observed_on':today.isoformat(),'end':str(plan['end']),'received':str(plan['received']),
                                     'plan':[{'name':bucket['name'],'amount':str(bucket['amount'])} for bucket in plan['buckets']],
                                     'confirmed_savings':None,'initial_spent':str(plan['spent']),'comparison_from':comparison_from.isoformat()}
        for identity,period in value['periods'].items():
            if period.get('closed'):continue
            first=day(period['comparison_from']);last=min(today,day(period['end']))
            collected=period.setdefault('observations',{})
            for key,row in observed.items():
                if first<=day(row['date'])<=last:
                    # Once recognised as a bill, a later unmatched view must not
                    # turn the same debit back into everyday spending.
                    if key in collected and collected[key]['kind']=='bills' and row['kind']=='everyday':continue
                    collected[key]=row
            if len(collected)>5000:raise ValueError('Salary-period observation limit reached')
            windows=period.get('windows',[])
            window_start=day(summary.get('requested_from'));window_end=day(summary.get('requested_to'))
            if summary.get('bank_data_status')=='complete' and window_start and window_end and first<=last:
                a=max(first,window_start);b=min(last,window_end)
                if a<=b:windows=merged_windows(windows+[[str(a),str(b)]])
            period['windows']=windows
            covered=bool(windows and day(windows[0][0])<=first and day(windows[0][1])>=last)
            period['actual']={'bills':str(sum((parse(row['amount']) for row in collected.values() if row['kind']=='bills'),ZERO)),
                              'everyday':str(sum((parse(row['amount']) for row in collected.values() if row['kind']=='everyday'),ZERO)),
                              'as_of':str(last),'coverage':'complete' if covered else 'partial','window_from':str(first),'window_to':str(last)}
            if last==day(period['end']) and today>last and (covered or today>last+timedelta(days=30)):
                period['closed']=True;period.pop('observations',None)
        value['periods']=dict(sorted(value['periods'].items())[-60:])
    return store().update(change)


def period_review(state):
    rows=[]
    for identity,row in sorted(state['periods'].items(),reverse=True):
        actual=row.get('actual',{});start=day(actual.get('window_from'))
        covered=actual.get('coverage')=='complete' and start is not None and start<=day(row.get('comparison_from') or identity)
        comparisons=[]
        for bucket in row['plan']:
            known=actual.get('bills') if bucket['name']=='Upcoming bills & repayments' else actual.get('everyday') if bucket['name']=='Estimated everyday spending' else row.get('confirmed_savings') if bucket['name']=='Savings contribution' else None
            amount=parse(known)
            comparisons.append({**bucket,'actual':amount,'difference':amount-parse(bucket['amount']) if amount is not None else None})
        rows.append({**row,'date':identity,'no_days':bool(day(row['comparison_from'])>day(actual.get('as_of',row['observed_on']))),'covered':covered,'comparisons':comparisons})
    return rows


def rental_performance(state,month,tax=None):
    start=date.fromisoformat(month+'-01');next_month=date(start.year+(start.month==12),start.month%12+1,1)
    entries=[row for row in state['rent_entries'] if start<=day(row['date'])<next_month]
    grouped={};totals={kind:ZERO for kind in KINDS}
    for row in entries:
        target=grouped.setdefault(row['property'],{'name':row['label'],'entries':[],'totals':{kind:ZERO for kind in KINDS}})
        target['entries'].append(row);target['totals'][row['kind']]+=parse(row['amount']);totals[row['kind']]+=parse(row['amount'])
    for target in grouped.values():
        values=target['totals'];target['before_tax_capital']=values['rent']-values['operating']-values['repair']-values['interest']
        target['cash_flow']=target['before_tax_capital']-values['capital']-values['tax']
    compatible=bool(tax and tax.get('rules') and day(tax['rules']['start'])<=start and next_month-timedelta(days=1)<=day(tax['rules']['end']))
    provision=tax['tax']/12 if compatible else None
    cash_flow=totals['rent']-sum((totals[k] for k in KINDS if k!='rent'),ZERO)
    after_provision=cash_flow-max(ZERO,provision-totals['tax']) if provision is not None else None
    return {'month':month,'properties':list(grouped.values()),'entries':sorted(entries,key=lambda r:r['date'],reverse=True),
            'totals':totals,'cash_flow':cash_flow,'provision':provision,'after_provision':after_provision}


def add_entry(property_row,kind,on,amount,note='',candidate=None):
    entry={'id':uuid.uuid4().hex[:12],'property':property_row['id'],'label':property_row['name'],'kind':kind,'date':on,'amount':amount,'note':note,'source':'Manual'}
    if candidate:entry.update(kind='rent',date=candidate['date'],amount=candidate['amount'],source='Bank observed',source_id=candidate['id'])
    store().update(lambda state:state['rent_entries'].append(entry))


def freeze(month):
    def change(state):
        latest=state.get('month_observations',{}).get(month)
        if latest is None and (state.get('latest_summary') or {}).get('month')==month:latest=state['latest_summary']
        if not latest or latest['month']!=month:raise ValueError('Refresh Finance for this month before saving a summary')
        if month in state['summaries']:raise ValueError('This monthly summary is already frozen; its original figures are preserved')
        if len(state['summaries'])>=60:raise ValueError('Monthly summary limit reached; export your records before starting a new history')
        state['summaries'][month]=deepcopy(latest)
    store().update(change)


def needs_update(projection,asset_view,bank_status,settings,tax):
    rows=[]
    if bank_status!='complete':rows.append({'message':'Bank coverage is '+bank_status,'url':'/finance-review'})
    for message in projection.get('warnings',[]):rows.append({'message':message,'url':'/finance-review#finance-forecast'})
    for item in asset_view.get('properties',[]):
        if item['stale'] or item['mortgage_stale']:rows.append({'message':item['name']+': update valuation or mortgage balance','url':'/finance/assets?edit='+item['id']})
    if not projection.get('payday'):rows.append({'message':'Set your next payday','url':'/finance-review#finance-forecast'})
    if settings.get('physical_cash_target') and settings.get('physical_cash_held') is None:rows.append({'message':'Record how much physical cash you hold','url':'/finance-review'})
    if tax and tax['gap']>0:rows.append({'message':'Rental-tax reserve still to build: GBP '+str(tax['gap']),'url':'/finance/tax'})
    return rows
