"""Pure manual salary scenario and receipt; never edits source finance records."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from textwrap import wrap
from finance.cash_scenarios import build as cash_scenario
from finance.projection import day, money, occurs, format_runway


def validate(values, today):
    mode = values.get('mode', 'replace')
    lump_mode = mode == 'lump'
    lump = money(values.get('lump_sum', '0') or '0') if lump_mode else Decimal(0)
    salary = Decimal(0) if lump_mode else money(values.get('salary'))
    existing = Decimal(0) if lump_mode else money(values.get('existing_salary', '0') or '0')
    other = Decimal(0) if lump_mode else money(values.get('other_income', '0') or '0')
    savings = Decimal(0) if lump_mode else money(values.get('savings_target', '0') or '0')
    if any(v is None or v < 0 or v > 10000000 for v in (salary, existing, other, savings, lump)):
        raise ValueError('Enter valid non-negative monthly amounts.')
    if mode not in {'replace', 'additional', 'lump'}:
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
                other=other, lump=lump, savings=savings, mode=mode, start=start, months=months)


def build(projection, values, today):
    inputs = validate(values, today)
    if not projection.get('valid'):
        raise ValueError('The finance forecast is incomplete. Refresh Finance review and confirm balances, repayment dates and a daily spending estimate first.')
    base = deepcopy(projection)
    salary = inputs['salary'] + inputs['existing']
    scenario = cash_scenario(base, dict(salary=str(salary), rent=str(inputs['other']),
        repair='0', vacancy='0', lump_sum=str(inputs['lump']), start=inputs['start'].isoformat(), months=str(inputs['months'])), today)
    end = occurs(inputs['start'], 1)
    bills = [event for event in base['events'] if inputs['start'] <= event['date'] < end]
    bills_total = sum((event['amount'] for event in bills), Decimal(0))
    daily = base.get('daily_cost', base['daily'])
    variable = daily * (end-inputs['start']).days
    # Roll actual opening cash forward to the first hypothetical payday once.
    prior_bills = sum((e['amount'] for e in base['events'] if today <= e['date'] < inputs['start']), Decimal(0))
    prior_days = max(0, (inputs['start']-today).days-1)
    payday_cash = base['cash'] - prior_bills - daily * prior_days + salary + inputs['other'] + inputs['lump']
    available = payday_cash - base['buffer'] - bills_total - variable
    savings = min(max(Decimal(0), available), inputs['savings'])
    spend = max(Decimal(0), available - savings)
    surplus = salary + inputs['other'] - bills_total - variable
    monthly_savings = min(max(Decimal(0), surplus), inputs['savings'])
    savings = monthly_savings
    spend = max(Decimal(0), available - savings)
    savings_base = deepcopy(base)
    if monthly_savings:
        savings_base['events'].extend({'date': occurs(inputs['start'], month), 'amount': monthly_savings,
            'name': 'Test savings transfer'} for month in range(inputs['months']))
        scenario = cash_scenario(savings_base, dict(salary=str(salary), rent=str(inputs['other']),
            repair='0', vacancy='0', lump_sum=str(inputs['lump']), start=inputs['start'].isoformat(), months=str(inputs['months'])), today)
    checkpoints = []
    for months in (1, 3, 6, 12):
        if months <= inputs['months']:
            point = cash_scenario(savings_base, dict(salary=str(salary), rent=str(inputs['other']),
                repair='0', vacancy='0', lump_sum=str(inputs['lump']), start=inputs['start'].isoformat(), months=str(months)), today)
            checkpoints.append((months, point['end_cash']))
    return dict(checkpoints=checkpoints, surplus=surplus, monthly_savings=monthly_savings, inputs=inputs, projection=base, forecast=scenario, bills=bills,
                bills_total=bills_total, variable=variable, payday_cash=payday_cash,
                savings=savings, spend=spend, shortfall=max(Decimal(0), -available), cycle_end=end-timedelta(days=1))


def receipt(result, today):
    lines = []
    def text(value=''):
        lines.extend(wrap(str(value), 42) or [''])
    def rule(): lines.append('-'*42)
    def section(title):
        rule(); text(title.center(42)); rule()
    def amount(label, value):
        right = f"GBP {value:,.2f}"
        if len(label) + len(right) + 1 <= 42:
            lines.append(label + right.rjust(42-len(label)))
        else:
            text(label); lines.append(right.rjust(42))
    data, base, forecast = result['inputs'], result['projection'], result['forecast']
    section('TEST FINANCE')
    text('SIMULATION - POTENTIAL SALARY' if data['mode'] != 'lump' else 'SIMULATION - LUMP SUM ONLY')
    text(f'Generated {today:%d %b %Y}')
    section('INCOME')
    if data['mode'] == 'lump':
        amount('One-off lump sum', data['lump'])
        text('No salary or other recurring income.')
    amount('Monthly take-home salary', data['salary'])
    if data['existing']: amount('Existing salary (additional mode)', data['existing'])
    amount('Other monthly income', data['other'])
    amount('TOTAL MONTHLY INCOME', data['salary']+data['existing']+data['other'])
    text(f'Income receipt date: {data["start"]:%d %b %Y}')
    section('CASH & RESERVES')
    amount('Current bank cash', base['cash'])
    reserve = base.get('reserve_details')
    if reserve:
        amount('Bank / emergency reserve', base['buffer']-reserve['gap']-reserve['tax_reserve'])
        amount('Physical cash top-up', reserve['gap'])
        amount('Tax reserve', reserve['tax_reserve'])
    amount('TOTAL PROTECTED', base['buffer'])
    amount('Existing cash above reserves', max(Decimal(0),base['cash']-base['buffer']))
    section('UPCOMING PAYMENTS')
    text(f'{data["start"]:%d %b} to {result["cycle_end"]:%d %b %Y}')
    for bill in result['bills']:
        estimated = bill.get('undated') or bill.get('basis') not in (None, 'Configured date', 'Repayment schedule', 'Annual renewal', 'Listed cash payment')
        amount(f'{bill["date"]:%d %b} {bill["name"]}' + (' *' if estimated else ''), bill['amount'])
    if not result['bills']: text('No scheduled payments in this period')
    text('* Estimated / reserved date: confirm day.')
    amount('PAYMENTS TOTAL', result['bills_total'])
    section('PAY PERIOD ALLOCATION')
    amount('Estimated everyday spending', result['variable'])
    amount('Per day (expected spending)', base.get('daily_cost', base['daily']))
    text('Expected spending, not a maximum allowance.')
    amount('INCOME SURPLUS', result['surplus'])
    text('Surplus excludes existing bank cash.')
    if data['savings']:
        amount('Monthly savings allocation', result['monthly_savings'])
        amount('Income left after saving', max(Decimal(0), result['surplus']-result['monthly_savings']))
    else:
        text('Savings target not set')
        amount('Available from income to save', max(Decimal(0),result['surplus']))
    amount('First-period total available', result['spend'])
    text('Total includes existing cash; not a recurring monthly spending allowance.')
    if result['shortfall']: amount('SHORTFALL after reserves', result['shortfall'])
    section('REPAYMENT OPTIONS')
    budget = result['spend'] if data['mode'] == 'lump' else max(Decimal(0), min(result['surplus']-result['monthly_savings'], result['spend']))
    options = base.get('repayment_options', [])
    if not options: text('No confirmed repayment balances available.')
    for item in options:
        name = str(item.get('name') or 'Repayment')
        text(name.upper())
        balance = money(item.get('remaining_balance', item.get('balance')))
        payment = money(item.get('monthly_payment', item.get('amount')))
        rate = money(item.get('apr', item.get('interest_rate')))
        final = day(item.get('end_date'))
        if balance is not None: amount('Remaining balance', balance)
        if payment: amount('Monthly amount freed on completion', payment)
        if final: text(f'Final payment: {final:%d %b %Y}')
        if item.get('payments_remaining') is not None: text(f'Payments remaining: {item["payments_remaining"]}')
        if balance is None or rate is None:
            text('Confirm balance/rate and early repayment terms before deciding.')
        elif balance > 0:
            if rate > 0:
                text(f'Interest rate: {rate}% - consider prioritising interest-bearing debt.')
            else:
                text('Interest-free: early payoff frees monthly cash but saves no interest.')
            amount('Extra repayment budget (shared)', budget)
            if budget >= balance:
                amount('Potential full payoff', balance)
                amount('Surplus left after payoff', budget-balance)
            else: text('Full payoff exceeds this period budget.')
            text('Option only; confirm settlement terms. Not deducted from this forecast. Budget is shared across all debts.')
    section('RUNWAY WITH TEST INCOME')
    if forecast['run_out']:
        text(f'Reserves breached: {forecast["run_out"]:%d %b %Y}')
        text(format_runway((forecast['run_out']-today).days, today))
    else: text(f'No shortfall through {forecast["end"]:%d %b %Y}')
    amount('Bank cash above reserves at end', forecast['end_cash'])
    amount('Test savings transfers over forecast', result['monthly_savings'] * data['months'])
    text('Bank cash excludes transferred savings. Savings shown are new test contributions only; no opening savings or interest.')
    for months, cash in result['checkpoints']:
        amount(f'{months} month(s): bank cash above reserves', cash)
    section('ASSUMPTIONS')
    text('Lump sum arrives once on the selected date. No future recurring income; no automatic savings transfers. Any payoff reduces cash runway.' if data['mode']=='lump' else 'Take-home salary; no salary tax deduction. Other income arrives on payday.')
    text('Monthly savings transfers are included in runway; savings remain assets outside spending cash.')
    text('Early repayment options are not included. Forecast is bounded, not unlimited.')
    for warning in base.get('warnings', []): text(warning)
    rule(); text('SIMULATION ONLY - LIVE RECORDS UNCHANGED'); rule()
    return '\n'.join(lines)+'\n'
