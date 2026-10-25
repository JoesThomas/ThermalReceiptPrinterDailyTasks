"""Amex-first treats reserve goals as destinations after essentials and card debt."""
from decimal import Decimal, ROUND_DOWN
from finance.money import parse, rounded

ZERO = Decimal(0)


def configure(base, inputs):
    if inputs['strategy'] != 'amex_first' or base.get('amex') is None:
        return None
    reserve = base.get('reserve_details') or {}
    gap = parse(reserve.get('gap'), ZERO)
    monzo = inputs.get('monzo_target', ZERO)
    bank = max(ZERO, base['buffer'] - gap - parse(reserve.get('tax_reserve'), ZERO) - monzo)
    minimum = inputs.get('minimum_bank_balance', ZERO)
    # The minimum is part of the bank target, not an additional savings goal.
    soft = bank + monzo + gap - minimum
    return dict(bank=bank, monzo=monzo, gap=gap, soft=soft, minimum=minimum,
                hard=max(ZERO, base['buffer'] - soft))


def free_cash(cash, policy, moved=ZERO):
    return cash + policy['soft'] - moved if policy else cash


def topup(cash, policy, moved, remaining_card, metadata, on):
    """Only withdraw physical cash after Amex and the bank targets are covered."""
    if not policy or remaining_card > ZERO:
        return None
    room = rounded(max(ZERO, cash + policy['gap'] - moved), rounding=ROUND_DOWN)
    amount = min(max(ZERO, policy['gap'] - moved), room)
    if amount <= ZERO:
        return None
    return dict(metadata or {}, date=on, amount=amount, funded=True, reserved_cash_topup=True)


def period_targets(cash_after_costs, policy, moved, cash_added, previous_monzo):
    if not policy:
        return {}
    available = max(ZERO, free_cash(cash_after_costs, policy, moved) + policy.get("minimum", ZERO))
    hsbc = min(policy['bank'], available)
    monzo = min(policy['monzo'], max(ZERO, available - hsbc))
    return dict(hsbc=hsbc, monzo=monzo, monzo_transfer=max(ZERO, monzo - previous_monzo),
                cash_transfer=cash_added, cash_pending=max(ZERO, policy['gap'] - moved),
                pending=max(ZERO, -cash_after_costs), moved=moved)


def bank_balances(base, forecast, monzo_target=ZERO):
    total = forecast['end_cash'] + base['buffer'] - forecast['reserved_total']
    policy = base.get('repayment_priority')
    if policy:
        monzo = min(monzo_target, max(ZERO, total - (policy['hard'] - policy.get('minimum', ZERO)) - policy['bank']))
    else:
        monzo = min(monzo_target, max(ZERO, total))
    return total - monzo, monzo
