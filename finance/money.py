"""Exact GBP parsing and rounding; float conversion belongs at legacy/output edges."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
PENNY = Decimal('0.01')
ZERO = Decimal(0)


def parse(value, default=None, *, rounded=True):
    if isinstance(value, bool): return default
    try:
        amount = Decimal(str(value))
        if not amount.is_finite(): return default
        return amount.quantize(PENNY, rounding=ROUND_HALF_UP) if rounded else amount
    except (InvalidOperation, ValueError, TypeError): return default


def total(values):
    return sum((parse(value, ZERO) for value in values), ZERO)
