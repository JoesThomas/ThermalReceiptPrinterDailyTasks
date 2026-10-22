"""Conservative allocation of observed salary and currently available cash."""
from datetime import timedelta
from decimal import Decimal
from finance.projection import day, money
from finance_trends import _parse_date
from web_control.payments import external_payments


def reserves(settings):
    from receipt.local_time import uk_today
    bank=max(Decimal(0),money(settings.get('hsbc_emergency_reserve'),Decimal(0)))
    target=max(Decimal(0),money(settings.get('physical_cash_target'),Decimal(0)))
    held=money(settings.get('physical_cash_held'))
    gap=max(Decimal(0),target-(held or Decimal(0)))
    from finance.annual_funds import protected_reserve
    tax_reserve = protected_reserve()
    from finance.annual_funds import store as fund_store
    reserve_label = 'Tax / annual cash pots' if fund_store().read()['enabled'] else 'Tax reserve'
    general=max(Decimal(0),money(settings.get('emergency_buffer'),Decimal(0)))
    return {'count_default_date': uk_today().isoformat(), 'bank':bank,'target':target,'held':held,'gap':gap,'date':day(settings.get('physical_cash_date')),
            'reserve_label':reserve_label,'tax_reserve':tax_reserve,'buffer':max(bank,general)+gap+tax_reserve,'percent':min(Decimal(100),(held or Decimal(0))/target*100) if target else None}


def build(salary,transactions,balances,projection,settings,goals,today):
    reserve=reserves(settings)
    hsbc=money(balances.get('HSBC',{}).get('available',balances.get('HSBC',{}).get('current')))
    reserve['hsbc_balance']=hsbc
    reserve['hsbc_gap']=max(Decimal(0),reserve['bank']-hsbc) if hsbc is not None else None
    recent=[s for s in salary if day(s.get('date')) and today-timedelta(days=29)<=day(s['date'])<=today and money(s.get('amount'),Decimal(0))>0]
    latest=max((day(s['date']) for s in recent),default=None)
    received=sum((money(s['amount'],Decimal(0)) for s in recent if day(s['date'])==latest),Decimal(0))
    spent=sum((money(t.get('spend_amount'),Decimal(0)) for t in external_payments(transactions)
               if latest and (d:=_parse_date(t)) and latest<=d<=today),Decimal(0))
    end=projection['payday']-timedelta(days=1) if projection.get('payday') else today+timedelta(days=30)
    bills=[e for e in projection['events'] if e['date']<=end]
    bills_cost=sum((e['amount'] for e in bills),Decimal(0))
    # Statement money stays protected even if its due date is after the next payday.
    protected_later=sum((e['amount'] for e in projection['events'] if e.get('amex_statement_protection') and e['date']>end),Decimal(0))
    protected_later += sum((e.get('cash_fund_reserved', Decimal(0)) for e in projection['events'] if e['date']>end), Decimal(0))
    bills_cost += protected_later
    variable=projection.get('daily_cost',projection['daily'])*(end-today).days
    manual=money(settings.get('salary_savings_target'))
    priorities=[];planning_error=False
    if manual is None:
        from finance.planning import load as load_plans
        try: priorities=load_plans().get('priorities',[])
        except (ValueError,TypeError,OSError): planning_error=True
    target=manual if manual is not None else sum((money(row['amount'],Decimal(0)) for row in priorities),Decimal(0)) if priorities else (goals or {}).get('monthly',{}).get('amount')
    valid=bool(not planning_error and latest and projection['valid'] and reserve['hsbc_gap'] is not None and reserve['hsbc_gap']==0)
    available=min(max(Decimal(0),received-spent),max(Decimal(0),(projection.get('cash') or Decimal(0))-projection['buffer'])) if valid else None
    from finance.annual_funds import plan as fund_plan
    fund_valid = bool(projection['valid'] and hsbc is not None and reserve['hsbc_gap'] == 0 and not planning_error)
    fund_budget = max(Decimal(0), min(hsbc - projection['buffer'], (projection.get('cash') or Decimal(0)) - projection['buffer']) - bills_cost - variable) if fund_valid else None
    covered = {identifier for e in bills for identifier in e.get('cash_fund_ids', [])}
    funds = fund_plan(fund_budget, today=today, valid=fund_valid, covered=covered)
    # Cash pots are earmarks, not investments: they can be funded without salary.
    fund_total = funds['total']
    buckets=[];left=available
    if valid:
        for label,wanted in [('Upcoming bills & repayments',bills_cost),('Estimated everyday spending',variable),('Tax & annual funds',fund_total),('Savings contribution',target or Decimal(0))]:
            if label == 'Tax & annual funds' and not funds['enabled']:
                continue
            allocated=min(left,wanted);left-=allocated
            buckets.append({'name':label,'amount':allocated,'required':wanted,'gap':wanted-allocated})
        buckets.append({'name':'Additional spending money','amount':left,'required':left,'gap':Decimal(0)})
        for bucket in buckets: bucket['percent']=float(bucket['amount']/available*100) if available else 0
    planned_savings = next(b['amount'] for b in buckets if b['name'] == 'Savings contribution') if valid else max(Decimal(0), money(target, Decimal(0)))
    surplus_valid = bool(projection['valid'] and projection.get('payday') and hsbc is not None and reserve['hsbc_gap'] == 0 and not planning_error)
    # Conservatively reserve every forecast cost against HSBC: another account's
    # cash must not make a transfer from HSBC appear affordable.
    headroom = min(hsbc - projection['buffer'], (projection.get('cash') or Decimal(0)) - projection['buffer']) if surplus_valid else None
    surplus = max(Decimal(0), headroom - bills_cost - variable - fund_total - planned_savings) if surplus_valid else None
    suggested_savings = max(Decimal(0), headroom - bills_cost - variable - fund_total) if surplus_valid else None
    savings_with_surplus = suggested_savings
    reasons=[]
    if not latest: reasons.append('No salary payment was identified in the available last 30 days. Check your salary payee setting.')
    if not projection['valid']: reasons.append('Complete bank balances, spending coverage and repayment assumptions are needed.')
    if reserve['hsbc_gap'] is None: reasons.append('The HSBC balance is unavailable.')
    elif reserve['hsbc_gap']>0: reasons.append('The HSBC emergency reserve is below target. Savings and spending allocations are withheld until that reserve is covered.')
    if planning_error: reasons.append('Private savings priorities could not be loaded; allocations are withheld.')
    if manual is None and not priorities and target is not None and not (goals or {}).get('shared',{}).get('complete',False): reasons.append('The ISA savings target is an estimate based on recorded contributions; confirm tax-year coverage before relying on it.')
    if reserve['target'] and reserve['held'] is None: reasons.append('Cash on hand is not recorded. The full physical cash target is reserved conservatively.')
    return {'fund_plan':funds,'reserve':reserve,'latest':latest,'received':received,'spent':spent,'end':end,'available':available,
            'bills':bills,'bills_cost':bills_cost,'variable':variable,'target':target,'buckets':buckets,'reasons':reasons,'valid':valid,'suggested_savings':suggested_savings,'surplus':surplus,'planned_savings':planned_savings,'savings_with_surplus':savings_with_surplus}
