"""Pure email-to-delivery parsing, independent of mail and printer clients."""
from receipt.local_time import uk_now
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from domain_models import DeliveryRecord

def parse(email_subject, email_body, reference_date=None, *, sanitize, parse_date, normalise_time) -> DeliveryRecord:
    email_subject = email_subject or ''
    email_body = email_body or ''
    full_text = email_subject + ' ' + email_body
    lower_text = full_text.lower()
    delivered_patterns = ('\\bhas been delivered\\b', '\\bwas delivered\\b', "\\bwe(?:'ve| have) delivered\\b", '\\bparcel delivered\\b', '\\bpackage delivered\\b', '\\bdelivered successfully\\b', '\\bdelivered to\\b', '\\bproof of delivery\\b')
    if any((re.search(pattern, lower_text) for pattern in delivered_patterns)):
        return None
    today = reference_date or uk_now().date()
    carrier = None
    carrier_patterns = (('EVRI', ('evri', 'myhermes', 'hermes parcel')), ('ROYAL MAIL', ('royal mail',)), ('AMAZON', ('amazon',)), ('DPD', ('dpd',)), ('DHL', ('dhl',)), ('YODEL', ('yodel',)), ('PARCELFORCE', ('parcelforce',)), ('UPS', ('ups', 'united parcel service')), ('FEDEX', ('fedex', 'federal express')))
    for carrier_name, identifiers in carrier_patterns:
        if any((identifier in lower_text for identifier in identifiers)):
            carrier = carrier_name
            break
    delivery_date = None
    weekday_match = re.search('\\b(?:arriving|arrives|expected|due)\\s+(?:on\\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\\b', lower_text, flags=re.IGNORECASE)
    if weekday_match:
        weekday_name = weekday_match.group(1).lower()
        weekday_numbers = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6}
        target_weekday = weekday_numbers[weekday_name]
        days_ahead = (target_weekday - today.weekday()) % 7
        delivery_date = today + timedelta(days=days_ahead)
    if not delivery_date:
        today_patterns = ('\\b(?:arriving|arrives|expected|due)\\s+(?:on\\s+)?today\\b', '\\bdelivery\\s+(?:is\\s+)?(?:expected\\s+)?today\\b', '\\bparcel\\b.{0,40}\\b(?:arriving|due|expected)\\s+today\\b', '\\bpackage\\b.{0,40}\\b(?:arriving|due|expected)\\s+today\\b')
        if any((re.search(pattern, lower_text, flags=re.IGNORECASE) for pattern in today_patterns)):
            delivery_date = today
    if not delivery_date:
        tomorrow_patterns = ('\\b(?:arriving|arrives|expected|due)\\s+(?:on\\s+)?tomorrow\\b', '\\bdelivery\\s+(?:is\\s+)?(?:expected\\s+)?tomorrow\\b', '\\bparcel\\b.{0,40}\\b(?:arriving|due|expected)\\s+tomorrow\\b', '\\bpackage\\b.{0,40}\\b(?:arriving|due|expected)\\s+tomorrow\\b')
        if any((re.search(pattern, lower_text, flags=re.IGNORECASE) for pattern in tomorrow_patterns)):
            delivery_date = today + timedelta(days=1)
    if not delivery_date:
        weekday_match = re.search('\\b(?:arriv\\w*|delivery|expected).{0,20}?\\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\\b', lower_text, flags=re.IGNORECASE)
        if weekday_match:
            weekday_name = weekday_match.group(1).lower()
            weekday_numbers = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6}
            target_weekday = weekday_numbers[weekday_name]
            days_ahead = (target_weekday - today.weekday()) % 7
            delivery_date = today + timedelta(days=days_ahead)
    if not delivery_date:
        date_patterns = ['(?:delivery|arrives?|arriving|delivering|delivered on|expected|eta|due)[\\s:,-]*(\\d{1,2}[-/]\\d{1,2}[-/]\\d{2,4})', '(\\d{1,2}[-/]\\d{1,2}[-/]\\d{2,4})(?:\\s+(?:delivery|arrives?|arriving|delivering|delivered))', '(?:delivery|arrives?|arriving|delivering|expected|due)[\\s:,-]*(\\d{4}-\\d{2}-\\d{2})']
        for pattern in date_patterns:
            match = re.search(pattern, full_text, flags=re.IGNORECASE)
            if not match:
                continue
            delivery_date = parse_date(match.group(1))
            if delivery_date:
                break
    if not delivery_date:
        text_date_pattern = '(?:delivery|arrives?|arriving|delivering|delivered on|expected|due).{0,40}?(\\d{1,2})(?:st|nd|rd|th)?\\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\\s+(\\d{4}))?'
        match = re.search(text_date_pattern, full_text, flags=re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month_text = match.group(2)
            year = int(match.group(3) or today.year)
            for fmt in ('%d %B %Y', '%d %b %Y'):
                try:
                    delivery_date = datetime.strptime(f'{day} {month_text} {year}', fmt).date()
                    break
                except ValueError:
                    pass
            if delivery_date and delivery_date < today - timedelta(days=30):
                try:
                    delivery_date = delivery_date.replace(year=delivery_date.year + 1)
                except ValueError:
                    pass
    if not delivery_date:
        return None
    time_from = None
    time_to = None
    time_patterns = ('\\b(\\d{1,2}:\\d{2})\\s*[-–—]\\s*(\\d{1,2}:\\d{2})\\b', '\\bbetween\\s+(\\d{1,2}:\\d{2})\\s+and\\s+(\\d{1,2}:\\d{2})\\b', '\\b(\\d{1,2}:\\d{2}\\s*[ap]\\.?m\\.?)\\s*[-–—]\\s*(\\d{1,2}:\\d{2}\\s*[ap]\\.?m\\.?)\\b', '\\bbetween\\s+(\\d{1,2}:\\d{2}\\s*[ap]\\.?m\\.?)\\s+and\\s+(\\d{1,2}:\\d{2}\\s*[ap]\\.?m\\.?)\\b')
    for pattern in time_patterns:
        match = re.search(pattern, full_text, flags=re.IGNORECASE)
        if not match:
            continue
        time_from = normalise_time(match.group(1))
        time_to = normalise_time(match.group(2))
        if time_from and time_to:
            break
    event_title = email_subject.strip()
    if len(event_title) < 3:
        if carrier:
            event_title = f'{carrier} Delivery'
        else:
            event_title = 'Package Delivery'
    from actions.delivery_summary import references
    metadata = references(email_subject, email_body)
    return {'event_title': sanitize(event_title), 'carrier': carrier, 'time_from': time_from, 'time_to': time_to, **metadata, 'delivery_date': delivery_date}
