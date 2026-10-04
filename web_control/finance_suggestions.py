"""Explainable finance checks; dismissal IDs stay in a private local file."""
from __future__ import annotations
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re

from finance.projection import day, key, matches, money
from finance_trends import _parse_date
from web_control.payments import external_payments

DISMISSED_FILE = Path(__file__).resolve().parent.parent / 'data' / 'finance_suggestions.json'


def _read():
    try:
        value = json.loads(DISMISSED_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def dismiss_suggestion(identity, today):
    if not re.fullmatch(r'[0-9a-f]{24}', identity):
        raise ValueError('Invalid suggestion')
    items = {k: v for k, v in _read().items() if day(v) and day(v) >= today}
    items[identity] = (today + timedelta(days=30)).isoformat()
    DISMISSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = DISMISSED_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(items, indent=2) + '\n', encoding='utf-8')
    temp.replace(DISMISSED_FILE)


def build_suggestions(projection, rows, annual, ended, charts, recurring, transactions, today):
    cards = []
    def add(title, detail, severity='review', target='commitments', evidence=()):
        fingerprint = f'{today:%Y-%m}|{title}|{detail}|{evidence}'
        identity = hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
        cards.append({'id': identity, 'title': title, 'detail': detail, 'severity': severity,
                      'target': target, 'evidence': list(evidence)})
    for warning in projection['warnings']:
        if 'Amex' in warning:
            add('Add the card repayment schedule', warning, 'attention', 'finance-forecast')
    if not projection['payday']:
        add('Set the next payday', 'Add the next payday to see the listed payments and spending allowance before that date.', 'review', 'finance-forecast')
    if not projection['valid']:
        add('Runway needs complete data', 'Refresh the bank data and check the cash balances before relying on a runway figure.', 'attention', 'finance-forecast')
    if projection['undated']:
        add('Add payment dates', 'Amounts with unknown dates are reserved conservatively. Adding their usual payment day improves the projection.',
            'attention', 'commitments', projection['undated'])
    if projection['safe_before_payday'] is not None and projection['safe_before_payday'] < 0:
        add('Known payments exceed cash before payday', f"The projection is short by £{abs(projection['safe_before_payday']):,.2f} before everyday spending. Review payment dates and balances.", 'attention', 'finance-forecast')
    upcoming = [e for e in projection['upcoming'] if e['date'] <= today + timedelta(days=14) and not e['undated']]
    if upcoming:
        total = sum((e['amount'] for e in upcoming), money(0))
        add('Payments in the next 14 days', f'£{total:,.2f} is listed. Keep this amount available alongside your everyday spending.',
            'review', 'commitments', [f"{e['date']:%d %b}: {e['name']} — £{e['amount']:,.2f} ({e['basis']})" for e in upcoming])
    unmatched = [r for r in rows if r['transaction'] is None]
    if unmatched:
        add('Check unmatched commitments', 'No bank match was found for these entries. This does not prove they are unpaid; confirm their date, amount and matching terms.',
            'review', 'commitments', [f"{r['item']['name']} — £{money(r['item']['amount']):,.2f}" for r in unmatched])
    renewals = [i for i in annual if i.get('days_until') is not None and i['days_until'] <= 30]
    if renewals:
        add('Annual renewals approaching', 'Check whether you want to renew and confirm the amount. Dated renewals are included in the runway.',
            'review', 'annual-subscriptions', [f"{i['name']}: {i['next_renewal']:%d %b} — £{money(i['amount']):,.2f}" for i in renewals])
    ending = [r['item'] for r in rows if day(r['item'].get('end_date'))
              and today <= day(r['item']['end_date']) <= today + timedelta(days=60)]
    if ending:
        add('Contracts ending soon', 'Check the final payment and whether the service continues after the contract ends.',
            'review', 'commitments', [f"{i['name']}: {i['end_date']}" for i in ending])
    debits = external_payments(transactions)
    still_charged = [i for i in ended if any(matches(i, tx) and (d := _parse_date(tx))
                    and day(i.get('end_date')) and day(i['end_date']) < d <= today for tx in debits)]
    if still_charged:
        add('Payments after a recorded contract end', 'A matching payment appeared after the end date. Check whether the contract rolled over or the date needs updating.',
            'attention', 'commitments', [i['name'] for i in still_charged])
    configured = [r['item'] for r in rows] + list(annual) + list(ended)
    for index,first in enumerate(configured):
        for second in configured[index+1:]:
            # Only explicit matching-term overlap; do not guess that different services are redundant.
            def terms(item):
                raw=item.get('match') or [item.get('name','')]
                return {key(t) for t in ([raw] if isinstance(raw,str) else raw) if key(t)}
            overlap=terms(first)&terms(second)
            if overlap and first.get('name') != second.get('name'):
                add('Review overlapping commitment matches', 'Two configured commitments use the same bank matching term. They may be separate services; review them before changing anything.',
                    'review','commitments',[str(first.get('name')),str(second.get('name'))])
    for candidate in recurring or []:
        name = str(candidate.get('name', 'Recurring merchant'))
        if any(key(i.get('name')) == key(name) or any(key(t) and key(t) in key(name)
                   for t in ([i.get('match')] if isinstance(i.get('match'), str) else (i.get('match') or []))) for i in configured):
            continue
        add('Review a possible recurring payment', f"{name}: approximately £{money(candidate.get('amount'), money(0)):,.2f}. Similar bank charges were observed 20–40 days apart; confirm before adding a commitment.", 'review', 'commitments')
    categories = charts.get('categories', [])
    if categories:
        top = max(categories, key=lambda c: c['amount'])
        add('Largest recent spending category', f"{top['name'].title()}: £{top['amount']:,.2f} over the available 30 days. Review the transactions if you want to reduce spending here.", 'info', 'finance-forecast')
    other = [c for c in categories if str(c['name']).upper() == 'OTHER' and c['amount'] > 0]
    if other:
        add('Review uncategorised spending', f"£{other[0]['amount']:,.2f} is categorised as Other. Check the merchant breakdown below before updating your local category rules.", 'review', 'finance-forecast')
    duplicates = {}
    for tx in debits:
        paid = _parse_date(tx)
        if not paid or not today - timedelta(days=29) <= paid <= today:
            continue
        label = str(tx.get('merchant_name') or tx.get('description') or 'Merchant')
        identity = (paid, label.casefold(), money(tx.get('spend_amount')))
        duplicates.setdefault(identity, []).append(label)
    repeats = [f'{on:%d %b}: {labels[0]} — £{amount:,.2f} × {len(labels)}'
               for (on, _, amount), labels in duplicates.items() if len(labels) > 1]
    if repeats:
        add('Review same-day repeat payments', 'These may be legitimate separate purchases. They remain in the totals; check your bank before treating them as duplicates.',
            'review', 'finance-forecast', repeats)
    dismissed = _read()
    return [c for c in cards if not day(dismissed.get(c['id'])) or day(dismissed[c['id']]) < today]
