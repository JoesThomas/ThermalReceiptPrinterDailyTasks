"""Pure manual salary scenario and receipt; never edits source finance records."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from textwrap import wrap
from finance.test_forecast import simulate, is_amex
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
    return dict(equal_savings=values.get('equal_savings') == 'on', invest_spare_cash=values.get('invest_spare_cash') == 'on', use_accounts=values.get('use_saved_accounts') == 'on', strategy=strategy, split=split, apr=apr, goal=goal, starting_savings=starting_savings, salary=salary, existing=existing if mode == 'additional' else Decimal(0),
                other=other, lump=lump, savings=savings, save_all=not lump_mode and values.get('save_all') == 'on', mode=mode, start=start, months=months)


def build(projection, values, today):
    inputs = validate(values, today)
    if not projection.get('valid'):
        raise ValueError('The finance forecast is incomplete. Refresh Finance review and confirm balances, repayment dates and a daily spending estimate first.')
    base = deepcopy(projection)
    if inputs['invest_spare_cash'] and inputs['salary']+inputs['existing']>0:
        reserve=base.get('reserve_details') or {}
        separate=money(reserve.get('gap'),Decimal(0))+money(reserve.get('tax_reserve'),Decimal(0))
        base['buffer']=max(base['buffer'],Decimal(1000)+separate)
    accounts=base.get('savings_accounts',[])
    from finance.savings_targets import allocate, link_regular_savings, prepare_cash_topup
    if inputs['use_accounts']:
        prepare_cash_topup(base,accounts,today,inputs['start'])
        inputs['starting_savings']=sum((row['balance'] for row in accounts if row['balance'] is not None),Decimal(0))
        link_regular_savings(base['events'],[row for row in accounts if row['balance'] is not None])
    forecast = simulate(base, inputs, today)
    account_plan=allocate(accounts,forecast['payments'] if inputs['use_accounts'] else [],forecast['events']+forecast['reserve_transfers'] if inputs['use_accounts'] else [],equal=inputs['equal_savings'])
    if (inputs['goal'] and forecast['goal_date'] is None or inputs['use_accounts'] and any(row['target'] and row['goal_date'] is None for row in account_plan['accounts'])) and inputs['mode'] != 'lump':
        extended_inputs = dict(inputs, months=60)
        while (occurs(inputs['start'], extended_inputs['months'])-today).days > 1826:
            extended_inputs['months'] -= 1
        extended = simulate(base, extended_inputs, today)
        forecast['extended_goal_date'] = extended['goal_date']
        forecast['extended_goal_months'] = extended_inputs['months']
        extended_accounts=allocate(accounts,extended['payments'] if inputs['use_accounts'] else [],extended['events']+extended['reserve_transfers'] if inputs['use_accounts'] else [],equal=inputs['equal_savings'])
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
        right = f"£{value:,.2f}"
        if len(label)+len(right)+1 <= 42: lines.append(label+right.rjust(42-len(label)))
        else: text(label); lines.append(right.rjust(42))
    data, base, forecast = result['inputs'], result['projection'], result['forecast']
    def goal_duration(reached):
        text('Estimated time to target:')
        text(format_runway((reached - today).days, today))
        if reached > forecast['end']: text('Beyond selected forecast; same pathway.')
    def goal_progress(starting, projected, target, added, *, enabled=True, reserved=Decimal(0)):
        current = min(Decimal(100), starting / target * 100)
        future = min(Decimal(100), projected / target * 100)
        text(f'Goal progress now: {current:.1f}%')
        if not enabled:
            text('Account pathway is disabled.'); return
        text(f'Projected progress at forecast end: {future:.1f}%')
        if reserved: amount('Average ongoing additions / month', (added-reserved) / data['months'])
        else: amount('Average saved per forecast month', added / data['months'])
        if starting >= target: text('Savings status: target already reached.')
        elif forecast['run_out']: text('Savings status: pathway has a funding shortfall. Review income and costs.')
        elif projected >= target: text('Savings status: target reached in the selected forecast.')
        elif added > 0: text('Savings status: progressing towards target on this pathway.')
        else: text('Savings status: no savings added in the selected forecast.')
    first = forecast['payments'][0]
    section('TEST FINANCE')
    text('SIMULATION - LUMP SUM ONLY' if data['mode']=='lump' else 'SIMULATION - POTENTIAL SALARY')
    text(f'Generated {today:%d %b %Y}')
    text(f'Forecast ends {forecast["end"]:%d %b %Y} ({data["months"]} months)')
    section('PAY PERIOD ALLOCATION')
    text(f'{data["start"]:%d %b} to {result["cycle_end"]:%d %b %Y}')
    if data['mode'] in {'lump', 'lump_income'}: amount('One-off lump sum',data['lump'])
    amount('Monthly take-home salary',data['salary'])
    if data['existing']: amount('Existing salary (additional mode)',data['existing'])
    amount('Other monthly income',data['other'])
    amount('TOTAL MONTHLY INCOME',data['salary']+data['existing']+data['other'])
    text(f'Income receipt date: {data["start"]:%d %b %Y}')
    strategies={'savings_first':'Savings first','amex_first':'Amex first','split':f'Split: {data["split"].normalize():f}% to Amex'}
    text('Strategy: '+strategies[data['strategy']])
    amount('Per day (expected spending)',base.get('daily_cost',base['daily']))
    amount('INCOME SURPLUS' if result['surplus']>=0 else 'INCOME FUNDING GAP',abs(result['surplus']))
    if data['save_all']: text('Saving all remaining income surplus.')
    elif not data['savings'] and not data['invest_spare_cash']: text('Savings target not set')
    if data['invest_spare_cash']:
        if data['salary']+data['existing']>0: text('Use spare bank cash with this strategy; keep at least £1,000 plus bills, spending and other reserves.')
        else: text('No salary: spare bank cash investment paused.')
    if result['shortfall']: amount('SHORTFALL after reserves',result['shortfall'])
    section('WHERE TO MOVE THIS PAYDAY')
    if data['use_accounts']: text('Savings split: equal between active goals.' if data['equal_savings'] else 'Savings split: saved contribution shares.')
    text('Extra transfers to make:')
    moved=Decimal(0)
    if data['use_accounts']:
        for account in result['account_plan']['accounts']:
            if account['first']:
                amount(account['name'],account['first']);moved+=account['first']
    unassigned=first['savings']-moved
    if unassigned: amount('Savings - choose an account',unassigned)
    if first['extra']: amount('Amex - extra repayment',first['extra'])
    if first['cash_repaid']: text(f'Includes £{first["cash_repaid"]:,.2f} from spare bank cash in the Amex repayment above.')
    if first['cash_invested']: text(f'Includes £{first["cash_invested"]:,.2f} from spare bank cash in the savings transfers above.')
    reserve=base.get('reserve_details') or {}
    if reserve.get('gap'):
        if base.get('cash_topup') and not forecast['reserve_transfers']:
            amount('Cash top-up - funding needed',reserve['gap'])
            text('Not credited to the cash goal yet.')
        else:
            amount('Cash top-up (already reserved)',reserve['gap'])
            if forecast['reserve_transfers']: text(f"Cash goal credited on {forecast['reserve_transfers'][0]['date']:%d %b %Y} in this plan.")
    if not moved and not unassigned and not first['extra'] and not reserve.get('gap'): text('No extra transfers in this period.')
    regular=[bill for bill in result['bills'] if bill.get('savings_account') or bill.get('category')=='savings' or 'hargreaves' in bill['name'].casefold() or bill['name'].casefold().strip()=='hlam regular saving']
    if regular:
        text('Already scheduled - do not send again:')
        for bill in regular: amount(f'{bill["date"]:%d %b} {bill["name"]}',bill['amount'])
        text('Included in the bills total below.')
        if any(not bill.get('savings_account') for bill in regular): text('Unlinked regular payments are not credited to an account goal. Enable saved accounts and check account names.')
    amount('Keep for bills / regular payments',first['costs'])
    amount('Keep for everyday spending',result['variable'])
    amount('Income left in bank',max(Decimal(0),first['budget']-first['extra']-first['savings']))
    if reserve.get('gap'): text('Cash top-up uses protected reserves; do not deduct it again.')
    section('CASH & RESERVES')
    amount('Current bank cash',base['cash'])
    reserve=base.get('reserve_details')
    if reserve:
        amount('Bank / emergency reserve',base['buffer']-reserve['gap']-reserve['tax_reserve'])
        if reserve['tax_reserve']: amount('Tax reserve',reserve['tax_reserve'])
    amount('TOTAL PROTECTED',base['buffer'])
    amount('Existing cash above reserves',max(Decimal(0),base['cash']-base['buffer']))
    card=base.get('amex')
    if card:
        section('AMEX PLAN')
        if card['balance'] is None:
            text('Balance unavailable. Listed repayments are included; enter Amex owed for payoff modelling.')
        else:
            if card.get('full_reserved'):
                amount('Balance owed now',card['balance'])
                text('Full balance reserved once today; already deducted in the forecast. Additional suggested repayment: £0.00.')
            else:
                text('THIS PAY PERIOD')
                text(f'{data["start"]:%d %b} to {result["cycle_end"]:%d %b %Y}')
                scheduled=sum((e['amount'] for e in result['bills'] if is_amex(e['name'])),Decimal(0))
                interest=max(Decimal(0),first['closing_card']-first['opening_card']+scheduled+first['extra'])
                amount('Balance at period start',first['opening_card'])
                if interest>=Decimal('0.005'): amount('Estimated interest this period',interest)
                amount('Scheduled repayment via direct debit this period',scheduled)
                amount('Extra repayment this period',first['extra'])
                amount('Balance at period end',first['closing_card'])
            text('WHOLE FORECAST')
            scheduled_total=sum((e['amount'] for e in forecast['events'] if is_amex(e['name'])),Decimal(0))
            amount('Scheduled repayments via direct debit over forecast',scheduled_total)
            amount('Extra repayments over forecast',forecast['extra_total'])
            amount('Amex owed at forecast end',forecast['card_end'])
            if forecast['payoff']: text(f'Projected Amex cleared: {forecast["payoff"]:%d %b %Y}')
            else: text('Amex not cleared within this forecast.' if forecast['card_end'] else 'No outstanding Amex balance.')
            if forecast['apr'] is None: text('Rate unknown: interest excluded. Enter APR to include estimated interest.')
            else:
                text(f'APR assumption: {forecast["apr"]}%')
                amount('Estimated interest over forecast',forecast['interest'])

    options=[item for item in base.get('repayment_options',[]) if not is_amex(item.get('name'))]
    if options: section('OTHER REPAYMENTS')
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

    if result['account_plan']['accounts']:
        section('RECORDED SAVINGS & INVESTMENTS')
        for index,account in enumerate(result['account_plan']['accounts']):
            if index: rule()
            text(account['name'].upper())
            if account['balance'] is None:
                text('Balance unavailable; excluded from totals and contribution allocation.')
                if account['target']: amount('Target balance', account['target'])
                text('Time to target unavailable until balance is recorded.'); continue
            amount('Current balance',account['balance'])
            if account.get('date'): text(f'Recorded {account["date"]}')
            else: text('Balance date not recorded.')
            if account['target']:
                amount('Target balance',account['target'])
                amount('Projected account balance',account['projected'])
                if account['projected']<account['target']:
                    amount('Still to save at forecast end',account['target']-account['projected'])
                goal_progress(account['balance'], account['projected'], account['target'], account['added'], enabled=data['use_accounts'],reserved=account['reserved_added'])
                reached=account['goal_date'] or account.get('extended_goal_date')
                if reached=='already': text('Target already reached.')
                elif reached:
                    text(f'Projected target date: {reached:%d %b %Y}' + (' (extended)' if not account['goal_date'] else ''))
                    goal_duration(reached)
                elif not data['use_accounts']: text('Enable saved account allocation to estimate time to target.')
                else:
                    text('No funded target date in this plan.')
                    text(f"Target not reached within the {forecast.get('extended_goal_months', data['months'])}-month planning period." if data['mode'] != 'lump' else 'Target not reached with this one-off lump sum.')
            else: text('No account balance target set.')
            if account['isa_contributions'] is not None:
                amount('Recorded ISA contributions this FY',account['isa_contributions'])
                text('ISA allowance progress is separate from the balance target.')
        if forecast['unallocated_savings']: amount('New savings not assigned to accounts',forecast['unallocated_savings'])
        if not data['use_accounts']: text('Account allocation disabled; overall goal uses the manual starting savings input.')
        if not result['account_plan']['complete']: text('Totals include known balances only.')

    section('SAVINGS PROJECTION')
    amount('Starting savings (separate to cash)',data['starting_savings'])
    amount('Extra savings transfers over forecast',forecast['savings_total']-forecast['cash_invested_total'])
    if data['invest_spare_cash']: amount('Spare bank cash invested over forecast',forecast['cash_invested_total'])
    if forecast['automatic_total']: amount('Scheduled savings over forecast',forecast['automatic_total'])
    if forecast['reserved_total']: amount('One-off cash top-up from reserves',forecast['reserved_total'])
    amount('Projected savings at forecast end',forecast['savings_end'])
    if not forecast['savings_total']: text('No extra savings transfers assumed in this test.' if forecast['automatic_total'] or forecast['reserved_total'] else 'No savings transfers assumed in this test.')
    else: text('Bank cash excludes transferred savings.')
    if data['goal']:
        section('SAVINGS GOAL')
        amount('Target savings balance',data['goal'])
        amount('Still to save at start',max(Decimal(0),data['goal']-data['starting_savings']))
        goal_progress(data['starting_savings'], forecast['savings_end'], data['goal'], forecast['savings_total']+forecast['automatic_total']+forecast['reserved_total'],reserved=forecast['reserved_total'])
        if data['starting_savings']>=data['goal']: text('Goal already met at the starting balance.')
        elif forecast['goal_date']:
            text(f'Projected goal date: {forecast["goal_date"]:%d %b %Y}')
            goal_duration(forecast['goal_date'])
        else:
            text(f'Goal not reached within the {data["months"]}-month forecast.')
            amount('Still to save at forecast end',max(Decimal(0),data['goal']-forecast['savings_end']))
            if forecast.get('extended_goal_date'):
                text(f'Extended projected goal date: {forecast["extended_goal_date"]:%d %b %Y}')
                goal_duration(forecast['extended_goal_date'])
            elif not forecast['savings_total'] and not forecast['automatic_total'] and not forecast['reserved_total']: text('No savings contribution selected or available; no funded goal date within the planning period.')
            else: text(f"No funded goal date within the {forecast.get('extended_goal_months', data['months'])}-month planning period.")
    section('RUNWAY WITH TEST INCOME')
    if forecast['run_out']:
        text(f'Reserves breached: {forecast["run_out"]:%d %b %Y}')
        text(format_runway((forecast['run_out']-today).days,today))
    else: text(f'No shortfall through {forecast["end"]:%d %b %Y}')
    reserve=base.get('reserve_details') or {}
    amount('Bank reserve kept',base['buffer']-money(reserve.get('gap'),Decimal(0))-money(reserve.get('tax_reserve'),Decimal(0)))
    amount('Bank cash above reserves at end',max(Decimal(0),forecast['end_cash']))
    if forecast['end_cash']<0: amount('Funding shortfall at forecast end',-forecast['end_cash'])
    for months,cash in result['checkpoints']:
        label='cash above reserves' if cash>=0 else 'funding shortfall'
        amount(f'{months} month(s): {label}',abs(cash))
    section('ASSUMPTIONS')
    text(f'Forecast: {data["months"]} months from {data["start"]:%d %b %Y}. Goal durations measured from {today:%d %b %Y}.')
    if data['invest_spare_cash']:
        text('Spare bank cash follows the selected strategy on salary paydays; Amex first repays Amex before extra savings. Protects £1,000, bills, everyday spending and other reserves. No salary means no spare cash investment. Uses selected account shares and targets.')
    else: text('Extra savings use recurring income surplus after bills, spending and reserves; existing bank cash is not used for extra savings.')
    text('Scheduled savings may use bank cash. Reserved cash top-up is separate.')
    text('Same income and costs continue; finite repayments stop at completion. No savings growth or new card purchases assumed. Goal dates are estimates; no transfers are made.')
    for warning in base.get('warnings',[]): text(warning)
    rule(); text('SIMULATION ONLY - LIVE RECORDS UNCHANGED'); rule()
    return '\n'.join(lines)+'\n'
