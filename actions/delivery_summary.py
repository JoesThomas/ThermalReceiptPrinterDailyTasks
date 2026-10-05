"""Compact delivery notices without claiming unrelated notices are one parcel."""
import hashlib
from html import unescape
import re
from collections import OrderedDict
from textwrap import wrap


def references(subject, body):
    text = subject + '\n' + body
    tracking = re.search(r'\b(?:tracking(?:\s+(?:number|id|reference))?|parcel\s+(?:number|id))\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{7,35})\b', text, re.I)
    order = re.search(r'\b(\d{3}-\d{7}-\d{7})\b', text)
    return {'tracking_ref':tracking.group(1).upper() if tracking and any(c.isdigit() for c in tracking.group(1)) else '',
            'order_ref':order.group(1) if order else '',
            'notice_id':hashlib.sha256(text.encode()).hexdigest()}


def item_title(delivery, *, decode_entities=True):
    title = str(delivery.get('event_title') or delivery.get('subject') or '')
    if decode_entities:
        title = unescape(title)
    title = re.sub(r"^(?:out for delivery|ordered|dispatched|shipped|arriving(?: today)?|delivered)\s*:\s*", '', title, flags=re.I)
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r"^(\d+)\s+['\"]", r'\1 x ', title).strip("'\" ")
    return title


def identity(delivery):
    carrier = str(delivery.get('carrier') or '').upper()
    if delivery.get('tracking_ref'):
        return (carrier, 'tracking', delivery['tracking_ref'])
    if delivery.get('order_ref') and item_title(delivery, decode_entities=False):
        # Match order updates for the same item, keeping different items separate.
        return (carrier, 'order-item', delivery['order_ref'], item_title(delivery, decode_entities=False).casefold())
    return (carrier, 'notice', delivery.get('notice_id') or
            (delivery.get('order_ref', ''), item_title(delivery, decode_entities=False), str(delivery.get('delivery_date'))))


def consolidate(deliveries):
    rows = OrderedDict()
    for delivery in deliveries:
        key = identity(delivery)
        title = str(delivery.get('event_title') or '').lower()
        rank = next((score for word, score in [('delivered', 5), ('out for delivery', 4), ('arriving', 3),
                    ('dispatched', 2), ('shipped', 2), ('ordered', 1)] if title.startswith(word)), 0)
        rank = (rank, bool(delivery.get('time_from') or delivery.get('time_to')))
        if key not in rows or rank > rows[key][0]:
            rows[key] = (rank, delivery)
    selected = [row for _, row in rows.values()]
    # A generic order update is superseded by item-specific tracking updates.
    # Distinct tracking references remain separate for split parcels.
    tracked = {(str(row.get('carrier') or '').upper(), row['order_ref'], item_title(row).casefold())
               for row in selected if row.get('tracking_ref') and row.get('order_ref')}
    return [row for row in selected if row.get('tracking_ref') or
            (str(row.get('carrier') or '').upper(), row.get('order_ref'), item_title(row).casefold()) not in tracked]


def summary_lines(deliveries, carrier, expected):
    groups = OrderedDict()
    seen = set()
    for delivery in consolidate(deliveries):
        key = identity(delivery)
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault((carrier(delivery),expected(delivery)),[]).append(delivery)
    lines = []
    for (name, when), notices in groups.items():
        name, when = unescape(str(name)), unescape(str(when))
        lines.append(name + (f' / {len(notices)} items' if len(notices)>1 else ''))
        for index, delivery in enumerate(notices,1):
            title = item_title(delivery)
            # Do not repeat generic carrier-only headings as item descriptions.
            if title.casefold() in {name.casefold(),(name+' delivery').casefold(),'package delivery'}:
                title = ''
            detail = title[:180]
            ref = delivery.get('tracking_ref') or delivery.get('order_ref')
            if ref:
                detail = detail or ('Order ...' + ref[-6:])
            if detail:
                lines.extend(wrap('[ ] ' + detail, 40, subsequent_indent='    '))
        lines.extend(wrap(when, 40, subsequent_indent='    '))
        lines.append('')
    return lines
