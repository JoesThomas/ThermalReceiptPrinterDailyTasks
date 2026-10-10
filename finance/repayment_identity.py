"""Canonical repayment records shared by debt totals and monthly commitments."""
import re
from finance.money import parse


def names(row):
    return {re.sub(r'[^a-z0-9]', '', str(row.get(field) or '').casefold())
            for field in ('name', 'monthly_commitment_name')} - {''}


def generic_amazon(row):
    return bool(re.fullmatch(
        r'amazon\s+monthly\s+payments?(?:\s*[-:(].*|\s+\d{4}-\d{2}-\d{2}.*)?',
        str(row.get('name') or '').strip(), re.I))


def unique_repayments(instalments, debts=()):
    """Prefer instalments, and named products over generic Amazon aliases.

    Generic aliases require a unique product with the same positive payment and
    outstanding balance. Amount alone cannot identify a debt. No bank match is
    needed to identify two file records; this does not mark either as paid.
    """
    rows = [row for row in [*instalments, *debts] if isinstance(row, dict)]
    detailed = [row for row in rows if not generic_amazon(row)]
    canonical = []
    for row in rows:
        if generic_amazon(row):
            payment = parse(row.get('monthly_payment', row.get('amount')))
            balance = parse(row.get('remaining_balance', row.get('balance')))
            candidates = [other for other in detailed
                          if other.get('type', 'payment_plan') == 'payment_plan'
                          and payment is not None and payment > 0
                          and balance is not None and balance > 0
                          and parse(other.get('monthly_payment', other.get('amount'))) == payment
                          and parse(other.get('remaining_balance', other.get('balance'))) == balance]
            identities = {tuple(sorted(names(other))) for other in candidates}
            if len(identities) == 1:
                continue
        aliases = names(row)
        if any(aliases & names(other) and (
                not generic_amazon(row) or not generic_amazon(other)
                or (parse(row.get('monthly_payment', row.get('amount'))) == parse(other.get('monthly_payment', other.get('amount')))
                    and parse(row.get('remaining_balance', row.get('balance'))) == parse(other.get('remaining_balance', other.get('balance')))))
               for other in canonical):
            continue
        canonical.append(row)
    return canonical
