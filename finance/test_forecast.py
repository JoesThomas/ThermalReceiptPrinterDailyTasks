"""Daily scenario cash flow with payday allocation and finite card repayment."""
from datetime import timedelta
from decimal import Decimal
from finance.projection import occurs

ZERO = Decimal(0)
CENT = Decimal('0.01')


def is_amex(name):
    key = ''.join(c for c in str(name).lower() if c.isalnum())
    return 'amex' in key or 'americanexpress' in key


def simulate(base, inputs, today):
    end = occurs(inputs['start'], inputs['months'])
    daily = base.get('daily_cost', base['daily'])
    income = inputs['salary'] + inputs['existing'] + inputs['other']
    card = base.get('amex') or {}
    balance = card.get('balance')
    known = balance is not None
    balance = balance or ZERO
    apr = inputs['apr'] if inputs['apr'] is not None else card.get('apr')
    rate = (apr or ZERO) / Decimal(100) / Decimal(365)
    cash = base['cash'] - base['buffer']
    events = {}
    for event in base['events']:
        events.setdefault(event['date'], []).append(event)
    paydays = {occurs(inputs['start'], month): month for month in range(inputs['months'])}
    periods = []; points = []; actual = []; transfers = ZERO; extra_total = ZERO
    run_out = None; payoff = None; goal_date = today if inputs['goal'] and inputs['starting_savings'] >= inputs['goal'] else None
    interest_total = ZERO; checkpoints = []; automatic_total=ZERO
    reserve_transfers=[];reserved_total=ZERO;topup=base.get('cash_topup')
    for offset in range((end-today).days):
        on = today + timedelta(days=offset)
        if known and balance > 0 and offset:
            interest = balance * rate
            balance += interest; interest_total += interest
        if on in paydays:
            month = paydays[on]; next_pay = occurs(inputs['start'], month+1)
            cash += income + (inputs['lump'] if month == 0 else ZERO)
            opening = cash + base['buffer']
            period_events = [e for e in base['events'] if on <= e['date'] < next_pay]
            noncard = sum((e['amount'] for e in period_events if not is_amex(e['name'])), ZERO)
            scheduled = sum((e['amount'] for e in period_events if is_amex(e['name'])), ZERO)
            if known:
                scheduled = min(scheduled, balance + balance*rate*(next_pay-on).days)
            costs = noncard + scheduled
            automatic=sum((e['amount'] for e in period_events if e.get('savings_account')),ZERO)
            variable = daily * (next_pay-on).days
            surplus = income - costs - variable
            budget = max(ZERO, min(surplus, cash-costs-variable)).quantize(CENT)
            debt_budget = max(ZERO, balance-scheduled) if known and not card.get('full_reserved') else ZERO
            strategy = inputs['strategy']
            if strategy == 'amex_first': extra = min(budget, debt_budget)
            elif strategy == 'split': extra = min(budget*inputs['split']/100, debt_budget).quantize(CENT)
            else: extra = ZERO
            available = budget-extra
            saving = available if inputs['save_all'] else min(available, max(ZERO,inputs['savings']-automatic))
            if strategy == 'savings_first': extra = min(budget-saving, debt_budget)
            balance = max(ZERO, balance-extra); cash -= extra+saving
            transfers += saving; extra_total += extra
            if known and balance <= CENT and payoff is None and card.get('balance', ZERO) > 0:
                payoff = on; balance = ZERO
            if inputs['goal'] and goal_date is None and inputs['starting_savings']+transfers+automatic_total+reserved_total >= inputs['goal'] and run_out is None:
                goal_date = on
            periods.append(dict(funded=run_out is None, date=on, end=next_pay-timedelta(days=1), salary=inputs['salary']+inputs['existing'],
                rent=inputs['other'], opening=opening, costs=costs, variable=variable, surplus=surplus,
                budget=budget, savings=saving, automatic_savings=automatic, extra=extra, planned_card=scheduled,
                balance_after_extra=balance, savings_total=transfers, cash_after_allocation=cash-costs-variable))
        for event in events.get(on, []):
            amount = event['amount']
            if known and is_amex(event['name']):
                amount = min(amount, balance)
                balance -= amount
                if balance <= CENT and payoff is None and card.get('balance', ZERO) > 0:
                    payoff = on; balance = ZERO
            if amount > 0:
                cash -= amount
                actual.append(dict(event, amount=amount, funded=run_out is None and cash-daily>=0))
                if event.get('savings_account'):
                    automatic_total+=amount
                    if inputs['goal'] and goal_date is None and inputs['starting_savings']+transfers+automatic_total+reserved_total>=inputs['goal'] and run_out is None and cash-daily>=0:
                        goal_date=on
        cash -= daily
        if topup and on==topup['date'] and cash>=0:
            # The gap was deducted in the starting protected buffer already.
            # Moving that reserved cash to the physical cash goal is one transfer.
            reserved_total=topup['amount']
            reserve_transfers.append(dict(topup,funded=True))
            if inputs['goal'] and goal_date is None and inputs['starting_savings']+transfers+automatic_total+reserved_total>=inputs['goal'] and run_out is None:
                goal_date=on
        if periods: periods[-1]['closing_card'] = balance if known else None
        if cash < 0 and run_out is None: run_out = on
        if offset % 7 == 0 or on == end-timedelta(days=1): points.append({'date': on, 'scenario': cash})
        for months in (1,3,6,12,24,36,48,60):
            if months <= inputs['months'] and on == occurs(inputs['start'], months)-timedelta(days=1): checkpoints.append((months, cash))
    return dict(valid=True, end=end-timedelta(days=1), end_cash=cash, run_out=run_out, payments=periods,
        points=points, checkpoints=checkpoints, events=actual, savings_total=transfers, extra_total=extra_total,
        card_end=balance if known else None, payoff=payoff, apr=apr, interest=interest_total,
        goal_date=goal_date, automatic_total=automatic_total,reserved_total=reserved_total,reserve_transfers=reserve_transfers,
        savings_end=inputs['starting_savings']+transfers+automatic_total+reserved_total)
