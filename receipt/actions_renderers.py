"""Actions rendering; compatibility helpers are injected by the live facade."""

def print_upcoming_deliveries(printer, deliveries, *, _context):
    _normalise_delivery_carrier = _context.get('_normalise_delivery_carrier')
    format_delivery_expected = _context.get('format_delivery_expected')
    left = _context.get('left')
    print_line = _context.get('print_line')
    printer_safe_text = _context.get('printer_safe_text')
    from receipt.sections import print_upcoming_deliveries as render
    return render(printer, deliveries, _normalise_delivery_carrier=_normalise_delivery_carrier, format_delivery_expected=format_delivery_expected, print_line=print_line, left=left, printer_safe_text=printer_safe_text)

def print_to_buy(printer, items, *, _context):
    centre = _context.get('centre')
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    print_line(printer, '=')
    printer.set(bold=True)
    centre(printer, 'TO BUY')
    printer.set(bold=False)
    print_line(printer, '-')
    if not items:
        left(printer, 'NO TO BUY ITEMS')
    for item in items:
        print_wrapped(printer, f'[ ] {printer_safe_text(item)}', width=40)
    print_line(printer, '-')

def print_future_tasks(printer, tasks, *, _context):
    centre = _context.get('centre')
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    pending = [task for task in tasks if not task['done']]
    print_line(printer, '=')
    printer.set(bold=True)
    centre(printer, 'FUTURE TASKS')
    printer.set(bold=False)
    print_line(printer, '-')
    if not pending:
        left(printer, 'NO UNFINISHED FUTURE TASKS')
    for task in pending:
        print_wrapped(printer, '[ ] ' + printer_safe_text(task['title']), width=40)
        if task['next_step']:
            print_wrapped(printer, 'Next: ' + printer_safe_text(task['next_step']), width=40)
    print_line(printer, '-')

def print_header(printer, location=None, *, _context):
    """Compact vintage machine-style header."""
    datetime = _context.get('datetime')
    printer_text = _context.get('printer_text')
    printer.set(align='center', font='a', bold=True, double_height=False, double_width=False)
    printer_text(printer, 'DAILY UPDATE\n')
    printer.set(bold=False)
    now = datetime.now()
    printer_text(printer, now.strftime('%a %d %b %Y  %H:%M:%S').upper() + '\n')
    printer_text(printer, f"{location['name'].upper()} / {location['region'].upper()}\n")

def print_calendar(printer, events, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    from receipt.sections import print_calendar as render
    return render(printer, events, print_line=print_line, left=left, print_wrapped=print_wrapped)

def print_google_doc(printer, text, upcoming_events, therapy_paid=None, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    therapy_payment_due = _context.get('therapy_payment_due')
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'TO DO')
    printer.set(bold=False)
    print_line(printer, '-')
    if therapy_payment_due(upcoming_events) and (not therapy_paid):
        print_wrapped(printer, f"[ ] {printer_safe_text('Pay for therapy')}", width=40)
    for line in text.splitlines():
        line = line.lstrip('\ufeff').strip()
        if not line.endswith('.'):
            continue
        line = line[:-1].strip()
        if not line:
            continue
        if therapy_paid and line.casefold() == 'pay for therapy':
            continue
        print_wrapped(printer, f'[ ] {printer_safe_text(line)}', width=40)

def print_random_document_lines(printer, text, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, "TODAY'S WORKOUT")
    printer.set(bold=False)
    print_line(printer, '-')
    from actions.receipt_workout import plan
    selected = plan()
    pending = [row for row in selected if not row['completed']]
    for row in pending:
        print_wrapped(printer, f"[ ] {printer_safe_text(row['title'])}", width=40)
    if pending:
        left(printer, 'Warm up 5 min; keep a comfortable pace.')
        if any((row.get('sets') for row in pending)):
            left(printer, 'Rest 60-90 sec between sets.')
            left(printer, 'Weights: controlled reps, no straining.')
        required = {item for row in pending for item in row.get('required', [])}
        if required:
            from actions.checklists import EQUIPMENT
            print_wrapped(printer, 'Equipment: ' + ', '.join((EQUIPMENT[key] for key in sorted(required))), width=40)
    if not pending:
        left(printer, "TODAY'S EXERCISES COMPLETE" if selected else 'NO EXERCISES SELECTED')

def print_footer(printer, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    printer_text = _context.get('printer_text')
    from receipt.local_time import uk_now
    from receipt.freshness import snapshot
    print_line(printer, '-')
    left(printer, 'Generated ' + uk_now().strftime('%d %b %Y %H:%M %Z'))
    states = [row.get('state') for row in snapshot().values()]
    if 'cached' in states:
        left(printer, 'Includes cached information')
    if any((state in ('partial', 'unavailable') for state in states)):
        left(printer, 'Some information incomplete')
    printer_text(printer, '\n\n\n')

def print_vehicle_expiry_checks(printer, vehicles, dvla_api_key, *, _context):
    ZoneInfo = _context.get('ZoneInfo')
    datetime = _context.get('datetime')
    expiring_vehicle_items = _context.get('expiring_vehicle_items')
    get_vehicle_status = _context.get('get_vehicle_status')
    left = _context.get('left')
    print_line = _context.get('print_line')
    printer_safe_text = _context.get('printer_safe_text')
    now = datetime.now(ZoneInfo('Europe/London'))
    if now.weekday() != 6:
        return
    if not vehicles or not dvla_api_key:
        return
    vehicles_due = []
    for vehicle in vehicles:
        registration = vehicle.get('registration')
        name = vehicle.get('name', registration)
        try:
            status = get_vehicle_status(registration, dvla_api_key)
            warnings = expiring_vehicle_items(status, today=now.date(), days=31)
            if warnings:
                vehicles_due.append((name, status, warnings))
        except Exception as error:
            print(f'Vehicle check error ({registration}): {error!r}')
    if not vehicles_due:
        return
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, 'VEHICLE REMINDERS')
    printer.set(bold=False)
    for name, status, warnings in vehicles_due:
        print_line(printer, '-')
        registration = status['registration']
        left(printer, printer_safe_text(f'{name} - {registration}'))
        for warning in warnings:
            expiry = warning['expiry_date']
            remaining = warning['days_remaining']
            left(printer, warning['type'])
            left(printer, f'EXPIRES {expiry:%d %b %Y} - {remaining} DAYS'.upper())
