"""Informational credit capacity; never contributes to cash or runway."""
from finance.money import parse


def summary(cards, balances=None):
    balances = balances or {}; result = []
    for card in cards:
        limit = parse(card['limit'])
        bank = balances.get('AMEX', {}) if card.get('provider') == 'AMEX' else {}
        used = parse(bank.get('current')) if bank else parse(card.get('used'))
        if used is not None: used = max(0, used)
        available = max(0, limit-used) if used is not None else None
        percent = max(0, used/limit*100) if used is not None else None
        result.append({**card, 'limit':limit,'used':used,'available':available,'percent':percent,'bar_percent':min(100, percent) if percent is not None else None,
                       'over':max(0,used-limit) if used is not None else 0,
                       'basis':'Bank-reported Amex balance' if bank and used is not None else 'Manual balance' if used is not None else 'Balance not available'})
    return result
