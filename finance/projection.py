"""Dated cash runway, using local commitments and observed variable spending."""
from __future__ import annotations
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re

from finance_trends import _parse_date
from web_control.payments import external_payments


def money(value, default=None):
    try:
        amount = Decimal(str(value))
        return amount.quantize(Decimal('0.01')) if amount.is_finite() else default
    except (InvalidOperation, ValueError, TypeError):
        return default


def day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def occurs(anchor, offset, repeat='monthly'):
    if repeat == 'yearly':
        year, month = anchor.year + offset, anchor.month
    else:
        year, zero = divmod(anchor.year * 12 + anchor.month - 1 + offset, 12)
        month = zero + 1
    return date(year, month, min(anchor.day, monthrange(year, month)[1]))


def matches(item, tx):
    terms = item.get('match') or [item.get('name', '')]
    if isinstance(terms, str):
        terms = [terms]
    text = ' '.join(str(tx.get(field) or '') for field in
                    ('merchant_name', 'description', 'spend_description')).casefold()
    expected = money(item.get('amount'))
    return bool(expected and any(str(term).strip().casefold() in text for term in terms if str(term).strip())
                and abs(abs(money(tx.get('amount'), Decimal(0))) - expected) <= Decimal('0.01'))


def payment_schedule(monthly, yearly, transactions, settings, today, horizon=365):
    end = today + timedelta(days=horizon)
    events, undated, warnings = [], [], []
    debits = [tx for tx in transactions if money(tx.get('amount')) is not None
              and str(tx.get('transaction_type') or tx.get('type') or '').upper() not in ('CREDIT', 'REFUND')
              and (money(tx.get('amount')) < 0 or str(tx.get('transaction_type') or tx.get('type') or '').upper() in ('DEBIT', 'CARD_PAYMENT'))]

    def add(item, due, amount, basis, unknown=False):
        amount = money(amount)
        if not amount or amount <= 0 or not today <= due <= end:
            return
        final = day(item.get('end_date'))
        if final and (due.year, due.month) > (final.year, final.month):
            return
        name = str(item.get('name') or 'Listed payment')
        events.append({'name': name, 'date': due, 'amount': amount, 'basis': basis,
                       'undated': unknown, 'category': item.get('category', 'bill')})

    names = {key(i.get('name')) for i in monthly}
    overrides = {key(i.get('monthly_commitment_name') or i.get('name')): i
                 for i in settings.get('commitments', []) if day(i.get('due_date'))}
    for original in monthly:
        item = dict(original)
        override = overrides.get(key(item.get('name')))
        if override:
            item['due_date'] = override['due_date']
            item['next_payment'] = override['due_date']
            item['amount'] = override.get('amount', item['amount'])
        amount = money(item.get('amount'))
        if not amount or amount <= 0:
            continue
        remaining = money(item.get('remaining_balance', item.get('balance')))
        if remaining is not None and remaining <= 0:
            continue
        count = item.get('payments_remaining')
        try:
            count = int(count) if count is not None else None
        except (ValueError, TypeError):
            count = None
        if count == 0:
            continue
        schedule = item.get('schedule')
        if isinstance(schedule, list) and schedule:
            for entry in sorted((e for e in schedule if isinstance(e, dict)),
                                key=lambda e: str(e.get('date') or e.get('due_date') or '')):
                if entry.get('paid'):
                    continue
                due = day(entry.get('date') or entry.get('due_date'))
                charge = money(entry.get('amount', amount))
                if not due or due < today or charge is None or charge <= 0:
                    continue
                candidate = dict(item, amount=charge)
                paid = any((d := _parse_date(tx)) and d <= today and abs((d - due).days) <= 2
                           and abs(money(tx.get('amount'), Decimal(0))) == charge
                           and (matches(candidate, tx) or (not item.get('match') and item.get('category') == 'repayment'))
                           for tx in debits)
                if paid:
                    continue
                if remaining is not None:
                    charge = min(charge, remaining)
                add(item, due, charge, 'Repayment schedule')
                if remaining is not None:
                    remaining -= charge
                    if remaining <= 0:
                        break
            continue
        anchor = day(item.get('next_payment') or item.get('due_date'))
        basis = 'Configured date'
        try:
            due_day = int(item.get('due_day'))
            if not 1 <= due_day <= 31:
                due_day = None
        except (ValueError, TypeError):
            due_day = None
        if due_day:
            anchor = date(today.year, today.month, min(due_day, monthrange(today.year, today.month)[1]))
        if not anchor:
            observed = [d for tx in debits if matches(item, tx)
                        if (d := _parse_date(tx)) and today - timedelta(days=45) <= d <= today]
            anchor = day(item.get('last_paid')) or (max(observed) if observed else None)
            basis = 'Estimated from last payment'
        unknown = anchor is None
        if unknown:
            undated.append(str(item.get('name') or 'Listed payment'))
            anchor = date(today.year, today.month, 1)
            basis = 'Date unknown; reserved conservatively'
        first_offset = max(0, (today.year - anchor.year) * 12 + today.month - anchor.month)
        launched = 0
        for offset in range(first_offset, first_offset + 14):
            due = occurs(anchor, offset)
            if due_day:
                due = date(due.year, due.month, min(due_day, monthrange(due.year, due.month)[1]))
            if due < today:
                if (due.year, due.month) != (today.year, today.month) or item.get('paid'):
                    continue
                due = today  # Unverified overdue item: reserve, do not claim it is unpaid.
                event_basis = 'Unverified past due; reserved today'
            else:
                event_basis = basis
            if (due.year, due.month) == (today.year, today.month) and item.get('paid'):
                continue
            if due > end or (count is not None and launched >= count):
                break
            charge = min(amount, remaining) if remaining is not None else amount
            add(item, due, charge, event_basis, unknown)
            launched += 1
            if remaining is not None:
                remaining -= charge
                if remaining <= 0:
                    break
    for item in yearly:
        anchor = day(item.get('renewal_date'))
        if not anchor:
            undated.append(str(item.get('name') or 'Annual subscription'))
            add(item, today, item.get('amount'), 'Renewal date unknown; reserved today', True)
            continue
        for offset in range(max(0, today.year - anchor.year), max(0, today.year - anchor.year) + 3):
            due = occurs(anchor, offset, 'yearly')
            observed = [d for tx in debits if matches(item, tx)
                        if (d := _parse_date(tx)) and d <= today and abs((d - due).days) <= 30]
            if due >= today and not observed:
                add(item, due, item.get('amount'), 'Annual renewal')
    # Explicit cash payments can cover card repayments and one-off commitments.
    for item in settings.get('commitments', []) + [dict(i, amount=-money(i.get('amount'), Decimal(0)))
                                                  for i in settings.get('forecast_events', [])
                                                  if money(i.get('amount'), Decimal(0)) < 0]:
        alias = key(item.get('monthly_commitment_name') or item.get('name'))
        if alias and alias in names:
            continue
        anchor = day(item.get('due_date') or item.get('date'))
        if not anchor:
            undated.append(str(item.get('name') or 'Listed payment'))
            add(item, today, item.get('amount'), 'Date unknown; reserved today', True)
            continue
        repeat = item.get('repeat', 'once')
        if repeat not in ('once', 'monthly', 'yearly'):
            warnings.append('A listed payment has an unsupported repeat rule.')
            continue
        offsets = range(14) if repeat == 'monthly' else range(3) if repeat == 'yearly' else range(1)
        start = max(0, (today.year - anchor.year) * 12 + today.month - anchor.month) if repeat == 'monthly' else max(0, today.year - anchor.year) if repeat == 'yearly' else 0
        for offset in offsets:
            due = anchor if repeat == 'once' else occurs(anchor, start + offset, repeat)
            payment_item = dict(item, match=item.get('match') or [item.get('name', '')])
            paid = any(matches(payment_item, tx) and (d := _parse_date(tx)) and d <= today
                       and abs((d - due).days) <= 2 for tx in debits)
            if not paid and not item.get('paid'):
                if due >= today:
                    add(item, due, item.get('amount'), 'Listed cash payment')
                elif due >= today - timedelta(days=29):
                    add(item, today, item.get('amount'), 'Unverified past due; reserved today')
    return sorted(events, key=lambda e: (e['date'], e['name'])), sorted(set(undated)), warnings


def build_projection(balances, transactions, monthly, yearly, settings, today,
                     savings=0, bank_status='complete', horizon=365):
    events, undated, warnings = payment_schedule(monthly, yearly, transactions, settings, today, horizon)
    cash = Decimal(0)
    balances_ok = True
    for provider in ('HSBC', 'MONZO'):
        row = (balances or {}).get(provider, {})
        value = money(row.get('available', row.get('current')))
        if value is None or row.get('currency', 'GBP') != 'GBP':
            balances_ok = False
        else:
            cash += value
    buffer = max(Decimal(0), money(settings.get('emergency_buffer'), Decimal(0)))
    recent = [tx for tx in external_payments(transactions)
              if (d := _parse_date(tx)) and today - timedelta(days=29) <= d <= today]
    # Remove actual configured bill matches before averaging variable spending.
    configured = monthly + yearly + settings.get('commitments', [])
    def fixed_match(item, tx):
        if matches(item, tx):
            return True
        anchor = day(item.get('next_payment') or item.get('due_date'))
        paid = _parse_date(tx)
        if item.get('category') != 'repayment' or not anchor or not paid:
            return False
        due = date(paid.year, paid.month, min(anchor.day, monthrange(paid.year, paid.month)[1]))
        return abs((paid - due).days) <= 2 and money(item.get('amount')) == abs(money(tx.get('amount'), Decimal(0)))
    variable = [tx for tx in recent if not any(fixed_match(item, tx) for item in configured)]
    daily = sum((money(tx.get('spend_amount'), Decimal(0)) for tx in variable), Decimal(0)) / 30
    override = money(settings.get('runway_daily_spend'))
    if override is not None and override >= 0:
        daily = override
    by_date = {}
    for event in events:
        by_date[event['date']] = by_date.get(event['date'], Decimal(0)) + event['amount']
    cash_days = total_days = None
    remaining = cash - buffer
    with_savings = remaining + max(Decimal(0), money(savings, Decimal(0)))
    timeline = []
    if remaining < 0:
        cash_days = 0
    if with_savings < 0:
        total_days = 0
    for offset in range(horizon + 1):
        on = today + timedelta(days=offset)
        cost = by_date.get(on, Decimal(0)) + (daily if offset else 0)
        remaining -= cost
        with_savings -= cost
        if remaining < 0 and cash_days is None:
            cash_days = offset
        if with_savings < 0 and total_days is None:
            total_days = offset
        timeline.append({'date': on, 'cash': remaining.quantize(Decimal('0.01'))})
    payday = day(settings.get('next_payday'))
    if payday and settings.get('payday_repeat') == 'monthly':
        anchor = payday
        first = max(0, (today.year - anchor.year) * 12 + today.month - anchor.month)
        for n in range(first, first + 3):
            payday = occurs(anchor, n)
            if payday > today:
                break
    if payday and not today < payday <= today + timedelta(days=horizon):
        payday = None
    before = [e for e in events if payday and e['date'] < payday]
    before_total = sum((e['amount'] for e in before), Decimal(0))
    days_to_payday = (payday - today).days if payday else None
    safe = cash - buffer - before_total if payday else None
    valid = balances_ok and bank_status == 'complete'
    if any(e['basis'] == 'Estimated from last payment' for e in events):
        warnings.append('Some dates are estimated from a past payment. Confirm the usual payment days.')
    planned_names = {key(i.get('monthly_commitment_name') or i.get('name'))
                     for i in monthly + settings.get('commitments', []) + settings.get('forecast_events', [])}
    for debt in settings.get('debts', []):
        alias = key(debt.get('monthly_commitment_name') or debt.get('name'))
        if money(debt.get('balance'), Decimal(0)) > 0 and alias not in planned_names:
            warnings.append('A listed debt has no scheduled repayment: ' + str(debt.get('name', 'Debt')))
            valid = False
    card_debt = money((balances or {}).get('AMEX', {}).get('current'), Decimal(0))
    configured_cards = monthly + settings.get('commitments', []) + settings.get('forecast_events', [])
    if card_debt > 0 and not any('amex' in key(i.get('name')) or 'americanexpress' in key(i.get('name')) for i in configured_cards):
        warnings.append('An Amex balance is owed but no repayment is scheduled. Add its payment amount and due date.')
        valid = False
    if not balances_ok:
        warnings.append('Live cash balances are unavailable; runway cannot be verified.')
    if bank_status != 'complete':
        warnings.append('Bank transactions are incomplete; a numeric runway is withheld.')
    if undated:
        warnings.append('Some payment dates are unknown. Their amounts are reserved conservatively.')
    if not recent and override is None:
        warnings.append('No variable spending history is available; add a daily spending estimate.')
        valid = False
    return {'cash': cash if balances_ok else None, 'buffer': buffer, 'daily': daily.quantize(Decimal('0.01')),
            'cash_days': cash_days if valid else None, 'total_days': total_days if valid else None,
            'valid': valid, 'horizon': horizon, 'undated': undated, 'warnings': warnings,
            'events': events, 'upcoming': [e for e in events if e['date'] <= today + timedelta(days=30)],
            'timeline': timeline[:31] if valid else [], 'payday': payday,
            'before_payday': before, 'before_payday_total': before_total,
            'safe_before_payday': safe if valid else None,
            'per_day_before_payday': (safe / days_to_payday).quantize(Decimal('0.01')) if valid and payday else None}
