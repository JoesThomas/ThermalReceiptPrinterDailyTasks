"""Pure manual salary scenario and receipt; never edits source finance records."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from textwrap import wrap
from finance.test_forecast import simulate
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
    strategy = values.get('strategy', 'savings_first')
    if strategy not in {'savings_first', 'amex_first', 'split'}:
        raise ValueError('Choose a repayment strategy.')
    split = money(values.get('amex_split', '50') or '50')
    apr = money(values.get('amex_apr')) if values.get('amex_apr', '').strip() else None
    if split is None or not 0 <= split <= 100 or (values.get('amex_apr', '').strip() and (apr is None or not 0 <= apr <= 100)):
        raise ValueError('Enter an Amex rate and split percentage between 0 and 100.')
    start = day(values.get('start'))
    if not start or not today <= start <= today + timedelta(days=365):
        raise ValueError('Choose a first payday between today and one year from today.')
    try:
        months = int(values.get('months', '12'))
    except (ValueError, TypeError):
        raise ValueError('Choose 1 to 60 forecast months.') from None
    if not 1 <= months <= 60 or (occurs(start, months) - today).days > 1826:
        raise ValueError('Choose a forecast ending within five years of today.')
    return dict(use_accounts=values.get('use_saved_accounts') == 'on', strategy=strategy, split=split, apr=apr, goal=goal, starting_savings=starting_savings, salary=salary, existing=existing if mode == 'additional' else Decimal(0),
                other=other, lump=lump, savings=savings, save_all=not lump_mode and values.get('save_all') == 'on', mode=mode, start=start, months=months)


def build(projection, values, today):
    inputs = validate(values, today)
    if not projection.get('valid'):
        raise ValueError('The finance forecast is incomplete. Refresh Finance review and confirm balances, repayment dates and a daily spending estimate first.')
    base = deepcopy(projection)
    accounts=base.get('savings_accounts',[])
    from finance.savings_targets import allocate
    if inputs['use_accounts']:
        inputs['starting_savings']=sum((row['balance'] for row in accounts if row['balance'] is not None),Decimal(0))
    forecast = simulate(base, inputs, today)
    account_plan=allocate(accounts,forecast['payments'] if inputs['use_accounts'] else [])
    if (inputs['goal'] and forecast['goal_date'] is None or inputs['use_accounts'] and any(row['target'] and row['goal_date'] is None for row in account_plan['accounts'])) and inputs['mode'] != 'lump':
        extended_inputs = dict(inputs, months=60)
        while (occurs(inputs['start'], extended_inputs['months'])-today).days > 1826:
            extended_inputs['months'] -= 1
        extended = simulate(base, extended_inputs, today)
        forecast['extended_goal_date'] = extended['goal_date']
        forecast['extended_goal_months'] = extended_inputs['months']
        extended_accounts=allocate(accounts,extended['payments'])
        for row,full in zip(account_plan['accounts'],extended_accounts['accounts']):
            row['extended_goal_date']=full['goal_date']
    first = forecast['payments'][0]
    bills = [event for event in forecast['events'] if inputs['start'] <= event['date'] <= first['end']]
    if inputs['use_accounts']: forecast['unallocated_savings']=account_plan['unallocated']
    else: forecast['unallocated_savings']=forecast['savings_total']
    return dict(account_plan=account_plan, checkpoints=forecast['checkpoints'], surplus=first['surplus'], monthly_savings=first['savings'],
        inputs=inputs, projection=base, forecast=forecast, bills=bills, bills_total=sum((e['amount'] for e in bills),Decimal(0)),
        variable=first['variable'], payday_cash=first['opening'], savings=first['savings'],
        spend=max(Decimal(0),first['cash_after_allocation']), shortfall=max(Decimal(0),-first['cash_after_allocation']),
        cycle_end=first['end'])


def receipt(result, today):
    lines = []
    def text(value=''): lines.extend(wrap(str(value), 42) or [''])
    def rule(): lines.append('-'*42)
    def section(title):
        rule(); text(title.center(42)); rule()
    def amount(label, value):
        right = f"GBP {value:,.2f}"
        if len(label)+len(right)+1 <= 42: lines.append(label+right.rjust(42-len(label)))
        else: text(label); lines.append(right.rjust(42))
    data, base, forecast = result['inputs'], result['projection'], result['forecast']
    first = forecast['payments'][0]
    section('TEST FINANCE')
    text('SIMULATION - LUMP SUM ONLY' if data['mode']=='lump' else 'SIMULATION - POTENTIAL SALARY')
    text(f'Generated {today:%d %b %Y}')
    section('INCOME')
    if data['mode'] in {'lump', 'lump_income'}: amount('One-off lump sum',data['lump'])
    amount('Monthly take-home salary',data['salary'])
    if data['existing']: amount('Existing salary (additional mode)',data['existing'])
    amount('Other monthly income',data['other'])
    amount('TOTAL MONTHLY INCOME',data['salary']+data['existing']+data['other'])
    text(f'Income receipt date: {data["start"]:%d %b %Y}')
    section('PAY PERIOD ALLOCATION')
    text(f'{data["start"]:%d %b} to {result["cycle_end"]:%d %b %Y}')
    strategies={'savings_first':'Savings first','amex_first':'Amex first','split':f'Split: {data["split"].normalize():f}% to Amex'}
    text('Strategy: '+strategies[data['strategy']])
    amount('Scheduled payments reserved',first['costs'])
    amount('Estimated everyday spending',result['variable'])
    amount('Per day (expected spending)',base.get('daily_cost',base['daily']))
    text('Expected spending, not a maximum allowance.')
    amount('INCOME SURPLUS' if result['surplus']>=0 else 'INCOME FUNDING GAP',abs(result['surplus']))
    text('Surplus excludes existing bank cash.')
    if data['save_all']: text('Saving all remaining income surplus.')
    elif not data['savings']: text('Savings target not set')
    amount('Extra Amex repayment applied',first['extra'])
    amount('Savings allocation this period',first['savings'])
    amount('Income left after allocation',max(Decimal(0),first['budget']-first['extra']-first['savings']))
    amount('Cash remaining after allocation',result['spend'])
    text('Includes existing cash, after costs and reserves; not a monthly allowance.')
    if result['shortfall']: amount('SHORTFALL after reserves',result['shortfall'])
    section('CASH & RESERVES')
    amount('Current bank cash',base['cash'])
    reserve=base.get('reserve_details')
    if reserve:
        amount('Bank / emergency reserve',base['buffer']-reserve['gap']-reserve['tax_reserve'])
        amount('Physical cash top-up',reserve['gap']); amount('Tax reserve',reserve['tax_reserve'])
    amount('TOTAL PROTECTED',base['buffer'])
    amount('Existing cash above reserves',max(Decimal(0),base['cash']-base['buffer']))
    card=base.get('amex')
    if card:
        section('AMEX PLAN')
        if card['balance'] is None:
            text('Balance unavailable. Listed repayments are included; enter Amex owed for payoff modelling.')
        else:
            amount('Balance owed now',card['balance'])
            if card.get('full_reserved'):
                text('Full balance reserved once today; already deducted in the forecast. Additional suggested repayment: GBP 0.00.')
            else:
                amount('Listed payments this period',first['planned_card'])
                amount('Surplus affordable before savings',first['budget'])
                amount('SUGGESTED EXTRA AMEX PAYMENT',first['extra'])
                text('Extra is limited by the unpaid balance, income surplus, cash after reserves and selected strategy.')
                baseline_saving=first['budget'] if data['save_all'] else min(first['budget'],data['savings'])
                amount('Savings redirected to repayment',max(Decimal(0),baseline_saving-first['savings']))
                amount('Estimated balance after this period',first['closing_card'])
            amount('Extra repayments over forecast',forecast['extra_total'])
            amount('Amex owed at forecast end',forecast['card_end'])
            if forecast['payoff']: text(f'Projected Amex cleared: {forecast["payoff"]:%d %b %Y}')
            else: text('Amex not cleared within this forecast.' if forecast['card_end'] else 'No outstanding Amex balance.')
            if forecast['apr'] is None: text('Rate unknown: interest excluded. Enter APR to include estimated interest.')
            else:
                text(f'APR assumption: {forecast["apr"]}%')
                amount('Estimated interest over forecast',forecast['interest'])
            text('Applied to forecast and savings goal. Listed payments stop at payoff. No new card purchases assumed; no real payment is made.')
    section('UPCOMING PAYMENTS')
    for bill in result['bills']:
        basis=bill.get('basis','')
        reserved=bool(bill.get('undated') or 'reserved' in basis.lower())
        estimated='estimated' in basis.lower()
        marker=' [R]' if reserved else ' *' if estimated else ''
        amount(f'{bill["date"]:%d %b} {bill["name"]}'+marker,bill['amount'])
    if not result['bills']: text('No scheduled payments in this period')
    text('[R] Undated/overdue amount reserved today; not proof of a missed payment. * Day estimated from a past payment.')
    amount('PAYMENTS TOTAL',result['bills_total'])
    section('OTHER REPAYMENTS')
    from finance.test_forecast import is_amex
    options=[item for item in base.get('repayment_options',[]) if not is_amex(item.get('name'))]
    if not options: text('No other confirmed repayment balances.')
    budget=max(Decimal(0),first['budget']-first['extra']-first['savings'])
    for item in options:
        text(str(item.get('name') or 'Repayment').upper())
        balance=money(item.get('remaining_balance',item.get('balance')))
        payment=money(item.get('monthly_payment',item.get('amount')))
        final=day(item.get('end_date'))
        rate=money(item.get('apr',item.get('interest_rate')))
        if balance is not None: amount('Remaining balance',balance)
        if payment: amount('Monthly cost freed on completion',payment)
        if final: text(f'Final payment: {final:%d %b %Y}')
        if item.get('payments_remaining') is not None: text(f'Payments remaining: {item["payments_remaining"]}')
        if balance is None or rate is None: text('Confirm balance/rate and early repayment terms before deciding.')
        elif balance>0 and budget>=balance: amount('Potential full payoff',balance)
    text('Finite listed schedules end automatically. Other early payoff options are not applied.')
    if result['account_plan']['accounts']:
        section('RECORDED SAVINGS & INVESTMENTS')
        for account in result['account_plan']['accounts']:
            text(account['name'].upper())
            if account['balance'] is None:
                text('Balance unavailable; excluded from totals and contribution allocation.'); continue
            amount('Current balance',account['balance'])
            if account.get('date'): text(f'Recorded {account["date"]}')
            else: text('Balance date not recorded.')
            if account['target']:
                amount('Target balance',account['target'])
                remaining=max(Decimal(0),account['target']-account['balance'])
                amount('Remaining to target',remaining)
                text(f'{min(Decimal(100),account["balance"]/account["target"]*100):.0f}% of balance goal')
                amount('First-period contribution',account['first'])
                amount('Contributions in selected forecast',account['added'])
                amount('Projected account balance',account['projected'])
                reached=account['goal_date'] or account.get('extended_goal_date')
                if reached=='already': text('Target already reached.')
                elif reached: text(f'Projected target date: {reached:%d %b %Y}' + (' (extended)' if not account['goal_date'] else ''))
                else: text('No funded target date in this plan.')
            else: text('No account balance target set.')
            if account['isa_contributions'] is not None:
                amount('Recorded ISA contributions this FY',account['isa_contributions'])
                text('ISA allowance progress is separate from the balance target.')
        amount('TOTAL RECORDED ACCOUNT BALANCES',result['account_plan']['current_total'])
        amount('New savings not assigned to accounts',forecast['unallocated_savings'])
        text('Account contributions share one savings budget. Finished goals redistribute their share to other selected goals; no growth or interest assumed.')
        if not data['use_accounts']: text('Account allocation disabled; overall goal uses the manual starting savings input.')
        if not result['account_plan']['complete']: text('Totals include known balances only.')
        text('These are hypothetical allocations, not recorded ISA subscriptions. Check shared contribution allowance before making deposits.')
    section('SAVINGS PROJECTION')
    amount('Starting savings (separate to cash)',data['starting_savings'])
    amount('Test savings transfers over forecast',forecast['savings_total'])
    amount('Projected savings at forecast end',forecast['savings_end'])
    periods=forecast['payments']
    examples={0, len(periods)-1}
    if len(periods)>1: examples.add(1)
    if forecast['payoff']:
        after=next((i for i,p in enumerate(periods) if p['date']>forecast['payoff']), None)
        if after is not None: examples.add(after)
    for index in sorted(examples):
        period=periods[index]
        amount(f'{period["date"]:%d %b %Y} savings',period['savings'])
    if not forecast['savings_total']: text('No savings transfers assumed in this test.')
    else: text('Bank cash excludes transferred savings.')
    if data['goal']:
        section('SAVINGS GOAL')
        amount('Target savings balance',data['goal'])
        amount('Still to save at start',max(Decimal(0),data['goal']-data['starting_savings']))
        if data['starting_savings']>=data['goal']: text('Goal already met at the starting balance.')
        elif forecast['goal_date']: text(f'Projected goal date: {forecast["goal_date"]:%d %b %Y}')
        elif not forecast['savings_total']: text('No savings contribution selected or available; no projected goal date.')
        else:
            text(f'Goal not reached within the {data["months"]}-month forecast. Extend forecast up to 60 months.')
            amount('Still to save at forecast end',max(Decimal(0),data['goal']-forecast['savings_end']))
            if forecast.get('extended_goal_date'):
                text(f'Extended projected goal date: {forecast["extended_goal_date"]:%d %b %Y}')
                text('Beyond selected cash forecast; uses the same strategy, costs and finite repayments.')
            else: text('No funded goal date within the five-year planning limit.')
        text('Goal uses actual period allocations and starting savings; excludes savings interest.')
    section('RUNWAY WITH TEST INCOME')
    if forecast['run_out']:
        text(f'Reserves breached: {forecast["run_out"]:%d %b %Y}')
        text(format_runway((forecast['run_out']-today).days,today))
    else: text(f'No shortfall through {forecast["end"]:%d %b %Y}')
    amount('Bank cash above reserves at end',max(Decimal(0),forecast['end_cash']))
    if forecast['end_cash']<0: amount('Funding shortfall at forecast end',-forecast['end_cash'])
    for months,cash in result['checkpoints']:
        label='cash above reserves' if cash>=0 else 'funding shortfall'
        amount(f'{months} month(s): {label}',abs(cash))
    section('ASSUMPTIONS')
    text('Take-home income only; lump sum once. Costs and savings recalculate each pay period. Starting savings are separate from bank cash. Reserves and everyday costs are protected before extra repayment/saving.')
    text('Amex interest uses a daily APR estimate when provided; actual statement interest/minimum payments may differ. Forecast assumes no new card purchases. Goal dates and payoff dates are estimates; no transfers are made.')
    for warning in base.get('warnings',[]): text(warning)
    rule(); text('SIMULATION ONLY - LIVE RECORDS UNCHANGED'); rule()
    return '\n'.join(lines)+'\n'
