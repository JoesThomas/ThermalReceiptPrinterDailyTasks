"""Pure hypothetical cash flow; no bank, salary or settings mutations."""
from datetime import timedelta
from decimal import Decimal
from finance.money import parse, ZERO
from finance.projection import day, occurs

DEFAULT={'salary':'0','rent':'0','vacancy':'0','repair':'0','start':'','months':'12'}


def validate(value):
    if not isinstance(value,dict):raise ValueError('Invalid scenario')
    for key in ('salary','rent','repair'):
        amount=parse(value.get(key))
        if amount is None or not ZERO<=amount<=10000000:raise ValueError('Enter non-negative scenario amounts')
    for key in ('months','vacancy'):
        try: amount=int(value.get(key))
        except (ValueError,TypeError):raise ValueError('Enter whole scenario months') from None
        if not 0<=amount<=24:raise ValueError('Scenario months must be between 0 and 24')
    if not 1<=int(value['months'])<=24 or int(value['vacancy'])>int(value['months']):raise ValueError('Vacancy cannot exceed scenario length')
    if not day(value.get('start')):raise ValueError('Choose the first hypothetical payment date')


def build(projection,value,today):
    validate(value)
    start=day(value['start'])
    if start<today:raise ValueError('Scenario start cannot be in the past')
    if not projection['valid']:return {'valid':False,'reason':'Complete live balances, repayment dates and spending coverage are needed.'}
    months=int(value['months']);end=occurs(start,months)
    if (end-today).days>760:raise ValueError('Choose a scenario starting soon enough for a two-year forecast')
    incomes={};rows=[]
    for month in range(months):
        on=occurs(start,month)
        salary=parse(value['salary']);rent=ZERO if month<int(value['vacancy']) else parse(value['rent'])
        incomes[on]=salary+rent;rows.append({'date':on,'salary':salary,'rent':rent,'vacant':month<int(value['vacancy'])})
    costs={}
    for event in projection['events']:
        costs[event['date']]=costs.get(event['date'],ZERO)+event['amount']
    base=projection['cash']-projection['buffer'];scenario=base;points=[];base_low=base;low=scenario;base_out=None;out=None
    daily=projection.get('daily_cost',projection['daily']);repair=parse(value['repair'])
    for offset in range((end-today).days):
        on=today+timedelta(days=offset)
        cost=costs.get(on,ZERO)+(daily if offset else ZERO)
        base-=cost;scenario-=cost;scenario+=incomes.get(on,ZERO)
        if on==start:scenario-=repair
        base_low=min(base_low,base);low=min(low,scenario)
        if base<0 and base_out is None:base_out=on
        if scenario<0 and out is None:out=on
        if offset%7==0 or on==end-timedelta(days=1):points.append({'date':on,'base':base,'scenario':scenario})
    lo=min([ZERO]+[min(p['base'],p['scenario']) for p in points]);hi=max([Decimal(1)]+[max(p['base'],p['scenario']) for p in points]);span=hi-lo
    for index,point in enumerate(points):
        point.update(x=20+index/max(1,len(points)-1)*560,y_base=180-float((point['base']-lo)/span)*150,y_scenario=180-float((point['scenario']-lo)/span)*150)
    return {'zero_y':180-float((ZERO-lo)/span)*150,'chart_min':lo,'chart_max':hi,'valid':True,'end':end-timedelta(days=1),'base_end':base,'end_cash':scenario,'base_low':base_low,'low':low,'base_out':base_out,'run_out':out,'points':points,'payments':rows,
            'base_line':' '.join(f"{p['x']},{p['y_base']}" for p in points),'scenario_line':' '.join(f"{p['x']},{p['y_scenario']}" for p in points),'repair':repair,'buffer':projection['buffer']}
