"""Show funded target allocations separately from mandatory protected money."""
from decimal import Decimal
from finance.money import format_pounds

ZERO = Decimal(0)


def transfers(page, base, first):
    policy = base.get('repayment_priority')
    if not policy:
        return False
    status = first['reserve_targets']
    if status['cash_transfer']:
        page.amount('Cash top-up funded this period', status['cash_transfer'])
    if status['monzo_transfer']:
        page.amount('Monzo top-up funded this period', status['monzo_transfer'])
    if status['pending']:
        page.amount('Still needed for HSBC / Monzo / Cash targets', status['pending'])
        page.text('Top-ups follow Amex and eligible early repayments. Bills and food/necessities come first.')
    if status['cash_pending'] and status['cash_pending'] != status['pending']:
        page.amount('Cash target still to fill', status['cash_pending'])
    return True


def keep(page, base, first):
    policy = base.get('repayment_priority')
    if not policy:
        return False
    status = first['reserve_targets']
    page.amount('HSBC target funded', status['hsbc'])
    page.text('HSBC target: ' + format_pounds(policy['bank']))
    if policy['monzo']:
        page.amount('Monzo target funded', status['monzo'])
        page.text('Monzo target: ' + format_pounds(policy['monzo']))
    other = policy['hard'] - policy.get('minimum', ZERO)
    if other:
        page.amount('Other protected reserves', other)
    return True
