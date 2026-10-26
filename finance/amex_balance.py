"""Outstanding-balance flags, separate from statement arrears and charged interest."""

from decimal import Decimal
from finance.money import parse, format_pounds
from finance.projection import day
from receipt.local_time import uk_today

ZERO = Decimal(0)


def assess(value=None, *, today=None, observed=None, simulated=False):
    if value is None:
        from finance.amex_protection import store

        value = store().read()
    today = today or uk_today()
    enabled = value.get("balance_alert_enabled", True)
    threshold = parse(value.get("balance_alert_threshold", "1000"))
    if (
        type(enabled) is not bool
        or threshold is None
        or not ZERO < threshold <= 10000000
    ):
        raise ValueError("Invalid Amex balance alert settings.")
    source = observed if observed is not None else value.get("evidence", {})
    stamp = day(source.get("checked_at"))
    fresh = bool(
        simulated
        or (
            source.get("amex_ok")
            and not source.get("refresh_failed")
            and stamp
            and 0 <= (today - stamp).days <= 1
        )
    )
    amount = parse(source.get("current"))
    currency = source.get("currency", "GBP")
    if currency != "GBP":
        amount = None
        fresh = False
    # An unavailable/stale zero cannot clear a previously reported positive debt.
    if not fresh and (amount is None or amount <= 0) and currency == "GBP":
        previous = parse(source.get("last_known_current"))
        amount = previous if previous is not None and previous > 0 else None
        stamp = day(source.get("last_known_checked_at")) or stamp
    owed = max(ZERO, amount) if amount is not None else None
    level = (
        "high"
        if owed is not None and owed > threshold
        else "outstanding"
        if owed
        else "clear"
        if fresh and owed == 0
        else "unknown"
    )
    if level == "high":
        title = "Amex balance above warning threshold"
    elif level == "outstanding":
        title = "Amex balance outstanding"
    elif level == "clear":
        title = "No outstanding Amex balance at last check"
    else:
        title = "Amex balance needs checking"
    if simulated:
        message = (
            "Simulated balance. Outstanding does not mean overdue or interest charged."
        )
    elif not fresh:
        message = "Last reported balance; refresh Finance to confirm. Outstanding does not by itself mean overdue or interest charged."
    else:
        message = "Outstanding does not by itself mean overdue or interest charged. Check the statement due date and repayment arrangement."
    if currency != "GBP":
        message = "A verified GBP balance is required for this threshold. Refresh Finance and check the selected Amex account."
    label = stamp.strftime("%d %b %Y") if stamp else "not available"
    return dict(
        enabled=enabled,
        threshold=threshold,
        threshold_text=format_pounds(threshold),
        amount=owed,
        amount_text=format_pounds(owed),
        level=level,
        title=title,
        message=message,
        checked=label,
        stale=not fresh,
        simulated=simulated,
        show=bool(
            enabled
            and (owed is not None and owed > 0 or level == "unknown" and bool(source))
        ),
    )


def view():
    try:
        return assess()
    except (ValueError, OSError):
        return dict(
            enabled=True,
            threshold=Decimal(1000),
            threshold_text="£1,000.00",
            amount=None,
            amount_text="Unavailable",
            level="unknown",
            title="Amex balance alerts unavailable",
            message="Check private data and refresh Finance.",
            checked="not available",
            stale=True,
            simulated=False,
            show=True,
        )


def print_status(printer, left, line, status):
    if not status["show"]:
        return
    line(printer)
    left(
        printer,
        "AMEX BALANCE WARNING" if status["level"] == "high" else "AMEX BALANCE CHECK",
    )
    if status["amount"] is not None:
        left(
            printer,
            ("Last reported owed: " if status["stale"] else "Balance owed: ")
            + status["amount_text"],
        )
    if status["level"] == "high":
        left(printer, "Above your " + status["threshold_text"] + " warning threshold.")
    if status["stale"]:
        left(printer, "Balance needs refresh; checked " + status["checked"] + ".")
    left(
        printer,
        "Not proof of overdue payment or interest. Check statement due date / Direct Debit.",
    )
    line(printer)


def receipt_status(page, amount, *, label="Simulated Amex balance"):
    from finance.amex_protection import store

    try:
        status = assess(
            store().read(),
            simulated=True,
            observed={"current": amount, "currency": "GBP"},
        )
    except (ValueError, OSError):
        page.text("Amex balance alert settings unavailable; check Finance.")
        return
    if status["show"] and status["level"] == "unknown":
        page.text(
            label + " unavailable; enter the amount owed to check this threshold."
        )
        return
    if status["show"]:
        page.text(
            label
            + ": "
            + status["amount_text"]
            + (
                " — ABOVE " + status["threshold_text"] + " warning threshold"
                if status["level"] == "high"
                else " outstanding"
            )
        )
        page.text("Outstanding does not mean overdue or interest charged.")
