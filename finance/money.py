"""Exact GBP parsing and rounding; float conversion belongs at legacy/output edges."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_HALF_EVEN

PENNY = Decimal("0.01")
ZERO = Decimal(0)


def parse(value, default=None, *, rounded=True):
    if isinstance(value, bool):
        return default
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return default
        return amount.quantize(PENNY, rounding=ROUND_HALF_UP) if rounded else amount
    except (InvalidOperation, ValueError, TypeError):
        return default


def total(values):
    return sum((parse(value, ZERO) for value in values), ZERO)


def rounded(value, *, rounding=ROUND_HALF_EVEN):
    """Round computed cash amounts; allocation callers explicitly round down."""
    return value.quantize(PENNY, rounding=rounding)


def format_pounds(value):
    """Shared presentation boundary for receipt and comparison amounts."""
    if value is None:
        return "Unavailable"
    return f"{'-' if value < 0 else ''}£{abs(value):,.2f}"
