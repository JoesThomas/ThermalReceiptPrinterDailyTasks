"""Receipt sections independent of network collection."""

def print_upcoming_deliveries(printer, deliveries, *, _normalise_delivery_carrier, format_delivery_expected, print_line, left, printer_safe_text):
    """
    Print only useful delivery information.

    Example:
        ROYAL MAIL
        Expected today
        AMAZON
        Expected 13:00-16:00

    The entire section is omitted when there are no deliveries.
    """
    from actions.delivery_state import record_deliveries
    deliveries = record_deliveries(deliveries, _normalise_delivery_carrier, format_delivery_expected)
    if not deliveries:
        return

    if isinstance(deliveries, dict):
        deliveries = [deliveries]

    deliveries = [
        item for item in deliveries
        if isinstance(item, dict)
    ]

    if not deliveries:
        return

    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, "UPCOMING DELIVERIES")
    printer.set(bold=False)
    print_line(printer, "-")

    from actions.delivery_summary import summary_lines
    for row in summary_lines(deliveries, _normalise_delivery_carrier, format_delivery_expected):
        left(printer, printer_safe_text(row))


def print_calendar(printer, events, *, print_line, left, print_wrapped):
    """Print today's events with their locations, without journey directions."""
    if not events:
        return

    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, "TODAY'S CALENDAR")
    printer.set(bold=False)
    print_line(printer, "-")

    for event in events:
        time_text = event.get("time") or ""
        title = event.get("title") or "EVENT"
        print_wrapped(printer, f"[ ] {time_text}  {title}", width=40)

        location = str(event.get("location") or "").strip()
        if location:
            print_wrapped(printer, f"LOCATION: {location}", width=40)

