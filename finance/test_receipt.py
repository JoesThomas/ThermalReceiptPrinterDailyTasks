"""Pure manual salary scenario and receipt; never edits source finance records."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from textwrap import wrap
from finance.cash_scenarios import build as cash_scenario
from finance.projection import day, money, occurs, format_runway


def validate(values, today):
    goal = money(values.get('savings_goal', '0') or '0')
    starting_savings = money(values.get('starting_savings', '0') or '0')
    mode = values.get('mode', 'replace')
    lump_mode = mode == 'lump'
    lump = money(values.get('lump_sum', '0') or '0') if mode in {'lump', 'lump_income'} else Decimal(0)
    salary = Decimal(0) if lump_mode else money(values.get('salary'))
    existing = Decimal(0) if lump_mode else money(values.get('existing_salary', '0') or '0')
    other = Decimal(0) if lump_mode else money(values.get('other_income', '0') or '0')
    savings = Decimal(0) if lump_mode else money(values.get('savings_target', '0') or '0')
    if any(v is None or v < 0 or v > 10000000 for v in (salary, existing, other, savings, lump, goal, starting_savings)):
        raise ValueError('Enter valid non-negative monthly amounts.')
    if mode not in {'replace', 'additional', 'lump', 'lump_income'}:
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
    return dict(goal=goal, starting_savings=starting_savings, salary=salary, existing=existing if mode == 'additional' else Decimal(0),
                other=other, lump=lump, savings=savings, save_all=not lump_mode and values.get('save_all') == 'on', mode=mode, start=start, months=months)


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
    monthly_savings = max(Decimal(0), surplus) if inputs['save_all'] else min(max(Decimal(0), surplus), inputs['savings'])
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
    if data['mode'] in {'lump', 'lump_income'}:
        amount('One-off lump sum', data['lump'])
        if data['mode'] == 'lump': text('No salary or other recurring income.')
        else: text('Lump sum once; salary and other income repeat monthly from the same date.')
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
    card = base.get('amex')
    if card:
        section('AMEX OWED & REPAYMENTS')
        if card['balance'] is None:
            text('Balance unavailable: enter Amex owed in scenario assumptions. Listed repayments are still included.')
        else: amount('Outstanding balance', card['balance'])
        if card['full_reserved']:
            text('Full balance reserved once today; already deducted in the forecast. No additional payoff deduction.')
        elif card['scheduled']:
            text('Listed Amex repayments are included in cash flow. Full balance is not deducted again. Interest/new purchases need updated payments.')
        elif card['balance'] == 0: text('No outstanding balance reported.')
    if card and card['balance'] is not None and card['balance'] > 0:
        section('AMEX REPAYMENT SUGGESTION')
        def is_amex(name):
            key = ''.join(c for c in str(name).lower() if c.isalnum())
            return 'amex' in key or 'americanexpress' in key
        planned = sum((bill['amount'] for bill in result['bills'] if is_amex(bill['name'])), Decimal(0))
        amount('Balance owed now', card['balance'])
        if card['full_reserved']:
            amount('Full balance reserved in forecast', card['balance'])
            text('Clearing this balance is already assumed. Additional suggested repayment: GBP 0.00. Confirm your statement due date.')
        else:
            amount('Repayments already in this period', planned)
            outstanding = max(Decimal(0), card['balance']-planned)
            affordable = max(Decimal(0), min(result['surplus'], result['spend']+result['monthly_savings']))
            extra = min(outstanding, affordable)
            amount('Income after bills & everyday costs', max(Decimal(0), result['surplus']))
            amount('Cash available before saving', result['spend']+result['monthly_savings'])
            amount('Affordable extra (smaller amount)', affordable)
            amount('SUGGESTED EXTRA AMEX PAYMENT', extra)
            amount('Total planned + suggested payment', min(card['balance'], planned+extra))
            amount('Estimated balance after payments', max(Decimal(0), outstanding-extra))
            savings_used = min(result['monthly_savings'], max(Decimal(0), extra-max(Decimal(0),result['surplus']-result['monthly_savings'])))
            amount('Savings redirected to repayment', savings_used)
            amount('Savings retained this period', result['monthly_savings']-savings_used)
            text('Extra = smaller of balance after listed payments and affordable income surplus. Preserves bank/tax/cash reserves and everyday spending; excludes existing cash surplus.')
            text('Consider paying this amount towards Amex, especially if interest is being charged. Check interest, minimum payment and settlement terms. Interest/new purchases are not included in the remaining balance estimate.')
            text('Alternative to saving the same money. Suggestion is not deducted from the forecast or savings goal until you change the scenario; no real payment is made.')
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
    amount('INCOME SURPLUS' if result['surplus'] >= 0 else 'INCOME FUNDING GAP', abs(result['surplus']))
    text('Surplus excludes existing bank cash.')
    if data['savings'] or data['save_all']:
        if data['save_all']: text('Saving all remaining income surplus.')
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
    amount('Bank cash above reserves at end', max(Decimal(0),forecast['end_cash']))
    if forecast['end_cash'] < 0:
        amount('Funding shortfall at forecast end', -forecast['end_cash'])
        text('Shortfall is additional funding needed to cover costs and preserve reserves, not an actual negative bank balance.')
    if result['monthly_savings']:
        amount('Test savings transfers over forecast', result['monthly_savings'] * data['months'])
        text('Bank cash excludes transferred savings. Savings shown are new test contributions only; no opening savings or interest.')
    else: text('No savings transfers assumed in this test.')
    for months, cash in result['checkpoints']:
        label = 'cash above reserves' if cash >= 0 else 'funding shortfall'
        amount(f'{months} month(s): {label}', abs(cash))
    if data['goal']:
        section('SAVINGS GOAL')
        amount('Target savings balance', data['goal'])
        amount('Starting savings (separate to cash)', data['starting_savings'])
        remaining = max(Decimal(0), data['goal']-data['starting_savings'])
        amount('Still to save', remaining)
        if not remaining: text('Goal already met at the starting balance.')
        elif result['monthly_savings']:
            from decimal import ROUND_CEILING
            payments = int((remaining/result['monthly_savings']).to_integral_value(rounding=ROUND_CEILING))
            if payments <= data['months']:
                reached = occurs(data['start'], payments-1)
                if forecast['run_out'] and forecast['run_out'] <= reached:
                    text('Goal not safely funded: reserves are breached before or on the projected goal date.')
                else:
                    text(f'Projected goal date: {reached:%d %b %Y}')
                    text(f'{payments} monthly savings contribution(s).')
            else:
                text(f'Goal not reached within the {data["months"]}-month forecast.')
                amount('Projected savings at forecast end', data['starting_savings']+result['monthly_savings']*data['months'])
        else: text('No savings contribution selected; no projected goal date.')
        text('Assumes savings are retained; excludes interest. Starting savings are not spending cash. Goal dates are estimates, not guarantees.')
    section('ASSUMPTIONS')
    if data['mode']=='lump_income': text('Lump sum is received once on the first payday. Monthly income is only the salary and other income entered in this test.')
    text('Lump sum arrives once on the selected date. No future recurring income; no automatic savings transfers. Any payoff reduces cash runway.' if data['mode']=='lump' else 'Take-home salary; no salary tax deduction. Other income arrives on payday.')
    if result['monthly_savings']: text('Monthly savings transfers are included in runway; savings remain assets outside spending cash.')
    text('Early repayment options are not included. Forecast is bounded, not unlimited.')
    for warning in base.get('warnings', []): text(warning)
    rule(); text('SIMULATION ONLY - LIVE RECORDS UNCHANGED'); rule()
    return '\n'.join(lines)+'\n'
