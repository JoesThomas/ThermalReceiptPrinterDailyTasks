"""Identify posted bill payments without treating every merchant debit as a bill."""
from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

from finance.money import PENNY, parse


def posted_date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (parsed.astimezone(ZoneInfo("Europe/London")) if parsed.tzinfo else parsed).date()


def debit(transaction):
    if str(transaction.get("status") or transaction.get("transaction_status") or "").upper() == "PENDING":
        return None
    kind = str(transaction.get("transaction_type") or transaction.get("type") or "").upper()
    amount = parse(transaction.get("amount"))
    if not amount or kind in {"CREDIT", "REFUND", "INCOME"}:
        return None
    return abs(amount) if amount < 0 or kind == "DEBIT" else None


def payment_candidates(item, transactions, today, *, start, end):
    terms = item.get("match") or []
    if isinstance(terms, str):
        terms = [terms]
    terms = [str(term).strip().casefold() for term in terms if term and str(term).strip()]
    if not terms:
        return []
    result = []
    for index, tx in enumerate(transactions):
        on = posted_date(tx.get("timestamp") or tx.get("transaction_date") or tx.get("date"))
        if on is None or not start <= on <= min(end, today):
            continue
        description = " ".join(str(tx.get(key) or "") for key in
                               ("merchant_name", "description", "spend_description")).casefold()
        if any(term in description for term in terms) and (amount := debit(tx)) is not None:
            result.append((index, on, amount))
    return result


def exact_amount(candidates, expected):
    return [match for match in candidates if expected is None or abs(match[2] - expected) <= PENNY]


def monthly_matches(items, transactions, today, *, reserved=()):
    """Use exact amounts first; only accept a changed debit when the match is unique."""
    start = today.replace(day=1)
    candidates = [
        payment_candidates(item, transactions, today,
                           start=max(start, posted_date(item.get("last_paid")) or start), end=today)
        for item in items
    ]
    expected = [parse(item.get("amount")) for item in items]
    matched = {}
    used = set(reserved)
    for row, options in enumerate(candidates):
        matches = exact_amount(options, expected[row])
        if match := max((match for match in matches if match[0] not in used),
                        key=lambda match: match[1], default=None):
            matched[row] = match
            used.add(match[0])

    for row, (item, options, amount) in enumerate(zip(items, candidates, expected)):
        if (row in matched or amount is None or len(options) != 1
                or item.get("category") in {"repayment", "savings"}
                or any(item.get(field) is not None for field in
                       ("schedule", "payments_remaining", "remaining_balance", "balance"))):
            continue
        match = options[0]
        index, on, paid = match
        if abs(paid - amount) <= PENNY or index in used:
            continue
        if any(other != row and any(option[0] == index for option in choices)
               for other, choices in enumerate(candidates)):
            continue
        anchor = posted_date(item.get("next_payment") or item.get("due_date") or item.get("last_paid"))
        due_day = item.get("due_day") or (anchor.day if anchor else None)
        try:
            due_day = int(due_day) if due_day else None
        except (ValueError, TypeError):
            continue
        if due_day is not None and not 1 <= due_day <= 31:
            continue
        if due_day:
            due = date(today.year, today.month, min(due_day, monthrange(today.year, today.month)[1]))
            if abs((on - due).days) > 7:
                continue
        matched[row] = match
        used.add(index)
    return matched


def monthly_contract_ended(item, today):
    """The month containing the end date is the final scheduled month."""
    from finance.instalment_settlement import is_settled

    final_day = posted_date(item.get("end_date"))
    return is_settled(item, today) or (
        final_day is not None and (today.year, today.month) > (final_day.year, final_day.month)
    )
