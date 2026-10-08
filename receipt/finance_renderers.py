"""Finance rendering; compatibility helpers are injected by the live facade."""

def print_subscription_changes(printer, changes, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    printer_safe_text = _context.get('printer_safe_text')
    if not changes:
        return
    print_line(printer, '-')
    printer.set(bold=True)
    left(printer, 'BILL CHANGES [B+F]')
    printer.set(bold=False)
    for change in changes:
        name = printer_safe_text(change.get('name', 'SUBSCRIPTION')).upper()
        old_amount = float(change.get('old_amount', 0))
        new_amount = float(change.get('new_amount', 0))
        difference = float(change.get('difference', 0))
        percentage = float(change.get('percentage', 0))
        left(printer, name[:40])
        left(printer, f'  £{old_amount:.2f} -> £{new_amount:.2f}')
        left(printer, f'  {difference:+.2f} GBP  {percentage:+.1f}%')

def print_instalment_status(printer, subscriptions_data, *, _context):
    _safe_amount = _context.get('_safe_amount')
    left = _context.get('left')
    print_line = _context.get('print_line')
    printer_safe_text = _context.get('printer_safe_text')
    instalments = subscriptions_data.get('instalments', [])
    if not instalments:
        return
    printer.set(bold=True)
    left(printer, 'INSTALMENTS')
    printer.set(bold=False)
    monthly_total = 0.0
    known_balance = 0.0
    for item in instalments:
        name = printer_safe_text(str(item.get('name', 'INSTALMENT')))
        amount = _safe_amount(item.get('amount'))
        monthly_total += amount
        balance = item.get('remaining_balance')
        payments_left = item.get('payments_remaining')
        left(printer, f'{name[:24]}')
        if payments_left is not None:
            left(printer, f' £{amount:.2f}/mo   {payments_left} payments left')
        else:
            left(printer, f' £{amount:.2f}/mo')
        if balance is not None:
            balance = _safe_amount(balance)
            known_balance += balance
            left(printer, f' £{balance:.2f} remaining')
    print_line(printer, '-')
    left(printer, f'INSTALMENTS / MONTH   £{monthly_total:.2f}')
    if known_balance > 0:
        left(printer, f'KNOWN BALANCE         £{known_balance:.2f}')

def print_subscription_status(printer, left, print_line, transactions, subscriptions_data=None, bank_data_status=None, *, _context):
    build_subscription_status = _context.get('build_subscription_status')
    receipt_right_amount = _context.get('receipt_right_amount')
    summarize_monthly_commitments = _context.get('summarize_monthly_commitments')
    status = build_subscription_status(transactions, subscriptions_data=subscriptions_data)
    monthly = status.get('monthly', [])
    if not monthly:
        return
    summary = summarize_monthly_commitments(monthly)
    paid = summary['paid']
    due = summary['due']
    paid_total = summary['paid_total']
    due_bills = summary['due_bills']
    due_savings = summary['due_savings']
    due_repayments = summary['due_repayments']
    remaining_total = summary['remaining_total']
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'MONTHLY COMMITMENTS [F+B]')
    printer.set(bold=False)
    print_line(printer, '-')
    printer.set(bold=True)
    left(printer, 'PAID [BANK MATCH]')
    printer.set(bold=False)
    if paid:
        for item in paid:
            name = item['name']
            display_names = {'HLAM Regular Saving': 'HLAM', 'Severn Trent Water': 'Water', 'Birmingham City Council': 'Council Tax'}
            name = display_names.get(name, name)
            for row in receipt_right_amount(name[:25], item['amount']):
                left(printer, row)
            if item.get('end_date'):
                left(printer, f"  CONTRACT ENDS {item['end_date']}")
    else:
        left(printer, 'None')
    print_line(printer, '-')
    printer.set(bold=True)
    for row in receipt_right_amount('PAID TOTAL', paid_total):
        left(printer, row)
    printer.set(bold=False)
    left(printer, '')
    printer.set(bold=True)
    left(printer, 'UNVERIFIED [BANK DATA INCOMPLETE]' if bank_data_status != 'complete' else 'DUE [FILE / NO BANK MATCH]')
    printer.set(bold=False)
    if due:
        for item in due:
            name = item['name']
            display_names = {'HLAM Regular Saving': 'HLAM', 'Severn Trent Water': 'Water', 'Birmingham City Council': 'Council Tax'}
            name = display_names.get(name, name)
            for row in receipt_right_amount(name[:25], item['amount']):
                left(printer, row)
            if item.get('end_date'):
                left(printer, f"  CONTRACT ENDS {item['end_date']}")
    else:
        left(printer, 'None')
    print_line(printer, '-')
    if bank_data_status != 'complete':
        left(printer, 'CHECK BANK CONNECTION / CONSENT')
        print_line(printer, '=')
        return
    if due:
        if due_bills:
            for row in receipt_right_amount('BILLS DUE', due_bills):
                left(printer, row)
        if due_savings:
            for row in receipt_right_amount('SAVINGS DUE', due_savings):
                left(printer, row)
        if due_repayments:
            for row in receipt_right_amount('REPAYMENTS DUE', due_repayments):
                left(printer, row)
    printer.set(bold=True)
    for row in receipt_right_amount('REMAINING', remaining_total):
        left(printer, row)
    printer.set(bold=False)
    print_line(printer, '=')

def print_annual_subscription_status(printer, left, print_line, subscriptions_data, transactions, today, *, _context):
    annual_subscription_rows = _context.get('annual_subscription_rows')
    receipt_right_amount = _context.get('receipt_right_amount')
    rows = annual_subscription_rows(subscriptions_data.get('yearly', []), transactions, today)
    if not rows:
        return
    print_line(printer, '=')
    left(printer, 'ANNUAL SUBSCRIPTIONS [F+B]')
    print_line(printer, '-')
    for item in rows:
        name = str(item.get('name') or 'SUBSCRIPTION')[:25]
        amount = float(item.get('amount') or 0)
        for row in receipt_right_amount(name, amount):
            left(printer, row)
        renewal = item['next_renewal']
        left(printer, f'  NEXT {renewal:%d %b %Y}' if renewal else '  ADD RENEWAL DATE')
        if item['bank_paid_date']:
            left(printer, f"  BANK MATCH {item['bank_paid_date']:%d %b %Y}")
        else:
            left(printer, '  PAYMENT UNVERIFIED')
        if item['last_paid_date']:
            left(printer, f"  LAST RECORDED {item['last_paid_date']:%d %b %Y}")
    print_line(printer, '=')

def print_financial_status(printer, balances, snapshot=None, *, _context):
    """
    Print the complete finance report.

    balances:
        Existing TrueLayer balance dictionary.

    snapshot:
        Result from build_finance_snapshot().
    """
    finance_quick_summary = _context.get('finance_quick_summary')
    format_money = _context.get('format_money')
    left = _context.get('left')
    load_regular_payments = _context.get('load_regular_payments')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'FINANCIAL STATUS')
    printer.set(bold=False)
    print_line(printer, '=')
    hsbc = balances.get('HSBC', {})
    monzo = balances.get('MONZO', {})
    amex = balances.get('AMEX', {})
    hsbc_available = float(hsbc.get('available', 0.0) or 0.0)
    monzo_available = float(monzo.get('available', 0.0) or 0.0)
    amex_owed = float(amex.get('current', 0.0) or 0.0)
    left(printer, f'HSBC AVAILABLE {format_money(hsbc_available)}')
    left(printer, f'MONZO AVAILABLE {format_money(monzo_available)}')
    left(printer, f'AMEX OWED {format_money(monzo_available)}')
    print_line(printer, '-')
    cash_available = hsbc_available + monzo_available
    net_after_amex = cash_available - amex_owed
    left(printer, f'CASH AVAILABLE {format_money(cash_available)}')
    left(printer, f'AFTER AMEX     {format_money(net_after_amex)}')
    if snapshot is None:
        print_line(printer, '=')
        return
    manual_assets = snapshot.get('manual_assets', [])
    if manual_assets:
        print_line(printer, '-')
        printer.set(bold=True)
        left(printer, 'OTHER ASSETS')
        printer.set(bold=False)
        for asset in manual_assets:
            name = str(asset.get('name', 'ASSET'))
            amount = float(asset.get('amount', 0.0) or 0.0)
            left(printer, f'{name[:20]:<20} {format_money(amount)}')
        print_line(printer, '-')
        net_position = float(snapshot.get('net_position', net_after_amex) or 0.0)
        left(printer, f'NET POSITION   {format_money(net_position)}')
    cashflow = snapshot.get('cashflow', {})
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'CASH FLOW - THIS MONTH')
    printer.set(bold=False)
    income = float(cashflow.get('income', 0.0) or 0.0)
    outgoings = float(cashflow.get('outgoings', 0.0) or 0.0)
    net_cashflow = float(cashflow.get('net', income - outgoings) or 0.0)
    left(printer, f'INCOMING        GBP {income:>9.2f}')
    left(printer, f'OUTGOING        GBP {outgoings:>9.2f}')
    print_line(printer, '-')
    left(printer, f'NET             GBP {net_cashflow:>9.2f}')
    categories = cashflow.get('categories', {})
    if categories:
        print_line(printer, '-')
        printer.set(bold=True)
        left(printer, 'SPENDING')
        printer.set(bold=False)
        category_order = ('food', 'eating_out', 'taxis', 'transport', 'shopping', 'other')
        printed_categories = set()
        for category in category_order:
            amount = float(categories.get(category, 0.0) or 0.0)
            if amount <= 0:
                continue
            printed_categories.add(category)
            name = category.replace('_', ' ').upper()
            left(printer, f'{name[:20]:<20} {format_money(amount)}')
        for category, value in categories.items():
            if category in printed_categories:
                continue
            amount = float(value or 0.0)
            if amount <= 0:
                continue
            name = str(category).replace('_', ' ').upper()
            left(printer, f'{name[:20]:<20} {format_money(amount)}')
    payments = snapshot.get('payments', {})
    payments_made = payments.get('made', [])
    payments_remaining = payments.get('remaining', [])
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'PAYMENTS MADE')
    printer.set(bold=False)
    if not payments_made:
        left(printer, 'NONE IDENTIFIED')
    else:
        for payment in payments_made:
            name = str(payment.get('name', 'PAYMENT'))
            amount = float(payment.get('amount', 0.0) or 0.0)
            left(printer, f'[X] {name[:17]:<17} {format_money(amount)}')
    print_line(printer, '-')
    printer.set(bold=True)
    left(printer, 'STILL TO PAY')
    printer.set(bold=False)
    if not payments_remaining:
        left(printer, 'NO KNOWN PAYMENTS')
    else:
        for payment in payments_remaining:
            name = str(payment.get('name', 'PAYMENT'))
            amount = float(payment.get('amount', 0.0) or 0.0)
            day = payment.get('day')
            if day:
                label = f'[ ] {name[:14]} {int(day):02d}'
            else:
                label = f'[ ] {name[:17]}'
            left(printer, f'{label:<21} {format_money(amount)}')
        print_line(printer, '-')
        remaining_total = float(payments.get('remaining_total', 0.0) or 0.0)
        left(printer, f'TOTAL STILL DUE {format_money(remaining_total)}')
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'DIRECT DEBITS')
    printer.set(bold=False)
    direct_debits = snapshot.get('direct_debits', [])
    if not direct_debits:
        left(printer, 'NONE RETURNED BY BANK')
    else:
        for payment in direct_debits:
            name = payment.get('name') or payment.get('reference') or payment.get('description') or 'DIRECT DEBIT'
            print_wrapped(printer, printer_safe_text(str(name)), width=40)
    print_line(printer, '-')
    printer.set(bold=True)
    left(printer, 'STANDING ORDERS')
    printer.set(bold=False)
    standing_orders = snapshot.get('standing_orders', [])
    if not standing_orders:
        left(printer, 'NONE RETURNED BY BANK')
    else:
        for payment in standing_orders:
            name = payment.get('name') or payment.get('reference') or payment.get('description') or 'STANDING ORDER'
            print_wrapped(printer, printer_safe_text(str(name)), width=40)
    regular_payments = load_regular_payments()
    subscriptions = [payment for payment in regular_payments if payment.get('type') == 'subscription']
    if subscriptions:
        print_line(printer, '=')
        printer.set(bold=True)
        left(printer, 'SUBSCRIPTIONS')
        printer.set(bold=False)
        subscription_total = 0.0
        for subscription in subscriptions:
            amount = float(subscription.get('amount', 0.0) or 0.0)
            subscription_total += amount
            name = str(subscription.get('name', 'SUBSCRIPTION'))
            left(printer, f'{name[:20]:<20} {format_money(amount)}')
        print_line(printer, '-')
        left(printer, f'MONTHLY TOTAL    {format_money(subscription_total)}')
    observations = snapshot.get('observations', [])
    if observations:
        print_line(printer, '=')
        printer.set(bold=True)
        left(printer, 'OBSERVATIONS')
        printer.set(bold=False)
        for observation in observations:
            print_wrapped(printer, '! ' + printer_safe_text(str(observation)), width=40)
    rest = snapshot.get('rest_of_month', {})
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'REST OF MONTH')
    printer.set(bold=False)
    remaining_bills = float(payments.get('remaining_total', 0.0) or 0.0)
    after_bills = float(rest.get('after_bills', cash_available - remaining_bills) or 0.0)
    days_remaining = int(rest.get('days_remaining', 0) or 0)
    daily_allowance = float(rest.get('daily_allowance', 0.0) or 0.0)
    left(printer, f'CASH AVAILABLE   {format_money(cash_available)}')
    left(printer, f'BILLS STILL DUE  {format_money(remaining_bills)}')
    print_line(printer, '-')
    left(printer, f'FREE AFTER BILLS {format_money(after_bills)}')
    left(printer, f'DAYS REMAINING   {days_remaining:>13}')
    left(printer, f'DAILY ALLOWANCE  {format_money(daily_allowance)}')
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'RUNWAY')
    printer.set(bold=False)
    monthly_burn = float(snapshot.get('monthly_burn', 0.0) or 0.0)
    essential_burn = float(snapshot.get('essential_burn', 0.0) or 0.0)
    left(printer, f'6M AVG SPEND     {format_money(monthly_burn)}')
    left(printer, f'ESSENTIAL BURN   {format_money(essential_burn)}')
    normal_runway = snapshot.get('normal_runway', {})
    essential_runway = snapshot.get('essential_runway', {})
    print_line(printer, '-')
    left(printer, 'CURRENT LIFESTYLE')
    left(printer, f"{normal_runway.get('months', 0):.2f} MONTHS / {normal_runway.get('days', 0)} DAYS")
    left(printer, 'ESSENTIAL ONLY')
    left(printer, f"{essential_runway.get('months', 0):.2f} MONTHS / {essential_runway.get('days', 0)} DAYS")
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'QUICK SUMMARY')
    printer.set(bold=False)
    summary_lines = finance_quick_summary(snapshot)
    for summary in summary_lines:
        print_wrapped(printer, printer_safe_text(summary), width=40)
    print_line(printer, '=')

def print_full_finance_report(printer, balances, direct_debits=None, standing_orders=None, subscriptions=None, spending_summary=None, *, _context):
    _runway_bar = _context.get('_runway_bar')
    _safe_amount = _context.get('_safe_amount')
    calculate_financial_runway = _context.get('calculate_financial_runway')
    centre = _context.get('centre')
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    direct_debits = direct_debits or []
    standing_orders = standing_orders or []
    subscriptions = subscriptions or []
    spending_summary = spending_summary or {}
    s = calculate_financial_runway(balances, direct_debits, standing_orders, subscriptions, spending_summary)
    salary_30 = _safe_amount(spending_summary.get('salary_30_days'))
    other_in_30 = _safe_amount(spending_summary.get('other_incoming_30_days'))
    total_in_30 = _safe_amount(spending_summary.get('total_incoming_30_days'))
    last_30 = _safe_amount(spending_summary.get('last_30_days'))
    net_flow_30 = _safe_amount(spending_summary.get('net_flow_30_days'))
    ninety_avg = _safe_amount(spending_summary.get('ninety_day_average'))
    essential_avg = _safe_amount(spending_summary.get('essential_monthly_burn'))
    trend_pct = 0.0
    if ninety_avg > 0 and last_30 > 0:
        trend_pct = (last_30 - ninety_avg) / ninety_avg * 100.0
    print_line(printer, '=')
    printer.set(bold=True)
    centre(printer, 'FINANCE CHECK')
    printer.set(bold=False)
    left(printer, 'ALL VALUES GBP')
    print_line(printer, '-')
    left(printer, 'SNAPSHOT')
    left(printer, f"HSBC             {s['hsbc']:>10.2f}")
    left(printer, f"MONZO             {s['monzo']:>10.2f}")
    left(printer, f"CASH              {s['cash']:>10.2f}")
    left(printer, f"AMEX OWED         {-s['amex']:>10.2f}")
    left(printer, f"NET CASH          {s['net_cash']:>10.2f}")
    print_line(printer, '-')
    left(printer, 'CASH FLOW / 30 DAYS')
    left(printer, f'SALARY            {salary_30:>10.2f}')
    left(printer, f'OTHER IN          {other_in_30:>10.2f}')
    left(printer, f'TOTAL IN          {total_in_30:>10.2f}')
    left(printer, f'SPENDING          {-last_30:>10.2f}')
    left(printer, f'NET FLOW          {net_flow_30:>+10.2f}')
    other_incomings = spending_summary.get('other_incomings', [])
    if other_incomings:
        print_line(printer, '-')
        left(printer, 'OTHER IN')
        for item in other_incomings[:5]:
            date_text = item['date'].strftime('%d %b').upper()
            name = printer_safe_text(item.get('name', 'INCOMING PAYMENT'))[:18]
            left(printer, f"{date_text} {name:<18} {item['amount']:>8.2f}")
    if direct_debits or standing_orders or subscriptions:
        print_line(printer, '-')
        left(printer, 'REGULAR OUTGOINGS')
        for item, label in [(x, 'DD') for x in direct_debits] + [(x, 'SO') for x in standing_orders] + [(x, 'SUB') for x in subscriptions]:
            name = printer_safe_text(str(item.get('name', 'PAYMENT')))[:20]
            amount = _safe_amount(item.get('amount'))
            left(printer, f'{label:<3} {name:<20} {amount:>8.2f}')
        left(printer, f"REGULAR TOTAL     {s['committed']:>10.2f}")
    print_line(printer, '-')
    left(printer, 'SPENDING')
    left(printer, f'90 DAY AVG        {ninety_avg:>10.2f}')
    left(printer, f'ESSENTIAL AVG     {essential_avg:>10.2f}')
    left(printer, f'LAST 30 DAYS      {last_30:>10.2f}')
    left(printer, f'TREND             {trend_pct:>9.1f}%')
    print_line(printer, '-')
    left(printer, 'RUNWAY')
    normal_days = s['normal_days']
    survival_days = s['survival_days']
    left(printer, 'NORMAL')
    left(printer, _runway_bar(normal_days))
    left(printer, f'{normal_days:>5.0f} DAYS / {normal_days / 30.44:>.1f} MO')
    left(printer, 'SURVIVAL')
    left(printer, _runway_bar(survival_days))
    left(printer, f'{survival_days:>5.0f} DAYS / {survival_days / 30.44:>.1f} MO')
    print_line(printer, '=')
    left(printer, 'SUMMARY')
    left(printer, f"NET CASH          {s['net_cash']:>10.2f}")
    left(printer, f'30D NET FLOW      {net_flow_30:>+10.2f}')
    left(printer, f'NORMAL RUNWAY     {normal_days:>7.0f} DAYS')
    left(printer, f'SURVIVAL RUNWAY   {survival_days:>7.0f} DAYS')
    print_line(printer, '-')
    if direct_debits:
        left(printer, 'DD  DIRECT DEBIT')
    if standing_orders:
        left(printer, 'SO  STANDING ORDER')
    if subscriptions:
        left(printer, 'SUB EST. SUBSCRIPTION')
    if spending_summary.get('salary_incomings'):
        left(printer, 'SAL LIKELY SALARY')
    print_wrapped(printer, 'RUNWAY BASED ON CURRENT NET CASH AND RECENT SPENDING.', width=40)
    print_line(printer, '=')

def print_subscriptions(printer, subscriptions_text, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'SUBSCRIPTIONS')
    printer.set(bold=False)
    print_line(printer, '-')
    items = [printer_safe_text(line.strip()) for line in (subscriptions_text or '').splitlines() if line.strip()]
    if not items:
        left(printer, 'NO SUBSCRIPTIONS LISTED')
        return
    for item in items:
        print_wrapped(printer, f'[ ] {item}', width=40)
    print_line(printer, '-')
