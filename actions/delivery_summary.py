"""Compact delivery notices without claiming unrelated notices are one parcel."""
import hashlib
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


def identity(delivery):
    carrier = delivery.get('carrier') or ''
    if delivery.get('tracking_ref'):
        return (carrier,'tracking',delivery['tracking_ref'])
    # One order can be split into several parcels. Only exact notices are collapsed.
    return (carrier,'notice',delivery.get('notice_id') or
            (delivery.get('order_ref',''),delivery.get('event_title',''),str(delivery.get('delivery_date'))))


def summary_lines(deliveries, carrier, expected):
    groups = OrderedDict()
    seen = set()
    for delivery in deliveries:
        key = identity(delivery)
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault((carrier(delivery),expected(delivery)),[]).append(delivery)
    lines = []
    for (name, when), notices in groups.items():
        lines.append(name + (f' / {len(notices)} notices' if len(notices)>1 else ''))
        lines.append(when)
        for index, delivery in enumerate(notices,1):
            title = re.sub(r'\s+',' ',str(delivery.get('event_title') or delivery.get('subject') or '')).strip()
            # Do not repeat generic carrier-only headings as item descriptions.
            if title.casefold() in {name.casefold(),(name+' delivery').casefold(),'package delivery'}:
                title = ''
            detail = title[:180]
            ref = delivery.get('tracking_ref') or delivery.get('order_ref')
            if ref:
                detail = (detail + ' / ' if detail else '') + 'Ref ...' + ref[-6:]
            if detail:
                lines.extend(wrap(('  '+str(index)+'. ' if len(notices)>1 else '  ') + detail,40))
        lines.append('')
    return lines
