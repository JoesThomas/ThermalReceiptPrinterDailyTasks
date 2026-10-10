"""Pure manual salary scenario and receipt; never edits source finance records."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from textwrap import wrap
from finance.cash_scenarios import build as cash_scenario
from finance.projection import day, money, occurs, format_runway


def validate(values, today):
    salary = money(values.get('salary'))
    existing = money(values.get('existing_salary', '0') or '0')
    other = money(values.get('other_income', '0') or '0')
    savings = money(values.get('savings_target', '0') or '0')
    if any(v is None or v < 0 or v > 10000000 for v in (salary, existing, other, savings)):
        raise ValueError('Enter valid non-negative monthly amounts.')
    mode = values.get('mode', 'replace')
    if mode not in {'replace', 'additional'}:
        raise ValueError('Choose how the potential salary should be used.')
    start = day(values.get('start'))
    if not start or not today <= start <= today + timedelta(days=365):
        raise ValueError('Choose a first payday between today and one year from today.')
    try:
        months = int(values.get('months', '12'))
    except (ValueError, TypeError):
        raise ValueError('Choose 1 to 24 forecast months.') from None
    if not 1 <= months <= 24 or (occurs(start, months) - today).days > 760:
        raise ValueError('Choose a forecast ending within two years of today.')
    return dict(salary=salary, existing=existing if mode == 'additional' else Decimal(0),
                other=other, savings=savings, mode=mode, start=start, months=months)


def build(projection, values, today):
    inputs = validate(values, today)
    if not projection.get('valid'):
        raise ValueError('The finance forecast is incomplete. Refresh Finance review and confirm balances, repayment dates and a daily spending estimate first.')
    base = deepcopy(projection)
    salary = inputs['salary'] + inputs['existing']
    scenario = cash_scenario(base, dict(salary=str(salary), rent=str(inputs['other']),
        repair='0', vacancy='0', start=inputs['start'].isoformat(), months=str(inputs['months'])), today)
    end = occurs(inputs['start'], 1)
    bills = [event for event in base['events'] if inputs['start'] <= event['date'] < end]
    bills_total = sum((event['amount'] for event in bills), Decimal(0))
    daily = base.get('daily_cost', base['daily'])
    variable = daily * (end-inputs['start']).days
    # Roll actual opening cash forward to the first hypothetical payday once.
    prior_bills = sum((e['amount'] for e in base['events'] if today <= e['date'] < inputs['start']), Decimal(0))
    prior_days = max(0, (inputs['start']-today).days-1)
    payday_cash = base['cash'] - prior_bills - daily * prior_days + salary + inputs['other']
    available = payday_cash - base['buffer'] - bills_total - variable
    savings = min(max(Decimal(0), available), inputs['savings'])
    spend = max(Decimal(0), available - savings)
    return dict(inputs=inputs, projection=base, forecast=scenario, bills=bills,
                bills_total=bills_total, variable=variable, payday_cash=payday_cash,
                savings=savings, spend=spend, shortfall=max(Decimal(0), -available), cycle_end=end-timedelta(days=1))


def receipt(result, today):
    lines = []
    def text(value=''):
        lines.extend(wrap(str(value), 42) or [''])
    def rule(): lines.append('-'*42)
    def amount(label, value):
        text(label)
        lines.append(f"GBP {value:,.2f}".rjust(42))
    data, base, forecast = result['inputs'], result['projection'], result['forecast']
    rule(); text('SIMULATION - POTENTIAL SALARY'); rule()
    text('MANUAL TEST - NOT ACTUAL MONEY RECEIVED')
    text(f'Generated {today:%d %b %Y}')
    text('Take-home salary; no salary tax deduction.')
    text('Mode: ' + ('Replace future salary' if data['mode']=='replace' else 'Additional monthly income'))
    amount('Potential monthly salary', data['salary'])
    if data['existing']: amount('Existing monthly salary assumed', data['existing'])
    amount('Other monthly income assumed', data['other'])
    text('Other income paid on the same day as salary.')
    text(f'First payday: {data["start"]:%d %b %Y}')
    text(f'Forecast: {data["months"]} monthly payments')
    rule(); text('OPENING CASH & PROTECTED RESERVES'); rule()
    amount('Current bank cash', base['cash'])
    amount('Protected buffer / cash top-up / tax', base['buffer'])
    amount('Estimated cash on first payday', result['payday_cash'])
    rule(); text('NEXT PAY PERIOD'); rule()
    text(f'{data["start"]:%d %b} to {result["cycle_end"]:%d %b %Y}')
    for bill in result['bills']:
        text(f'{bill["date"]:%d %b} {bill["name"]}')
        lines.append(f"GBP {bill['amount']:,.2f}".rjust(42))
    if not result['bills']: text('No scheduled payments in this period')
    amount('Bills / subscriptions / repayments', result['bills_total'])
    amount('Estimated everyday spending', result['variable'])
    amount('Savings contribution', result['savings'])
    amount('Additional spending allowance', result['spend'])
    if result['shortfall']: amount('SHORTFALL after protected reserves', result['shortfall'])
    rule(); text('PROJECTED RUNWAY WITH TEST INCOME'); rule()
    if forecast['run_out']:
        text('Protected cash falls below zero on:')
        text(forecast['run_out'].strftime('%d %b %Y'))
        text(format_runway((forecast['run_out']-today).days, today))
    else:
        text(f'No shortfall through {forecast["end"]:%d %b %Y}')
        text('This does not mean unlimited runway.')
    amount('Cash above reserves at forecast end', forecast['end_cash'])
    text('Savings allocation above is a first-period suggestion; no savings transfers are assumed in the runway.')
    for warning in base.get('warnings', []): text('ASSUMPTION: '+warning)
    rule(); text('SIMULATION ONLY - LIVE RECORDS UNCHANGED'); rule()
    return '\n'.join(lines)+'\n'
