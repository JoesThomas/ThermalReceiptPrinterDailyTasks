"""Food rendering; compatibility helpers are injected by the live facade."""

def print_food_shop_check(printer, food_shop_text, *, _context):
    centre = _context.get('centre')
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    print_line(printer, '=')
    printer.set(bold=True)
    centre(printer, 'FOOD SHOP')
    printer.set(bold=False)
    print_line(printer, '-')
    items = [printer_safe_text(line.strip()) for line in (food_shop_text or '').splitlines() if line.strip()]
    if not items:
        left(printer, 'NO FOOD SHOP ITEMS')
        return
    for item in items:
        print_wrapped(printer, f'[ ] {item}', width=40)
    print_line(printer, '-')

def print_shopping_list(printer, shopping_list_text, *, _context):
    centre = _context.get('centre')
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    printer_safe_text = _context.get('printer_safe_text')
    print_line(printer, '=')
    printer.set(bold=True)
    centre(printer, 'SHOPPING LIST')
    printer.set(bold=False)
    print_line(printer, '-')
    items = [printer_safe_text(line.strip()) for line in (shopping_list_text or '').splitlines() if line.strip()]
    if not items:
        left(printer, 'NO SHOPPING LIST ITEMS')
        return
    for item in items:
        print_wrapped(printer, f'[ ] {item}', width=40)
    print_line(printer, '-')
