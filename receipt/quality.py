"""Advisory receipt checks; warnings never assert that paper output was verified."""
import re
from datetime import datetime, timezone


def check(pages, freshness=None):
    warnings = []
    for name, text in pages.items():
        lines = text.splitlines()
        wide = [index+1 for index,line in enumerate(lines) if len(line.rstrip()) > 42 and not line.startswith('[[RECEIPT_IMAGE_')]
        if wide: warnings.append({'page':name,'message':f'{len(wide)} lines exceed 42 columns and may wrap or clip. First line: {wide[0]}.'})
        if len(lines) > 180: warnings.append({'page':name,'message':f'Long page: {len(lines)} lines. Consider compact detail or fewer headlines.'})
        if 'UPCOMING DELIVERIES' in text:
            section = text.split('UPCOMING DELIVERIES',1)[1].split('EXERCISES',1)[0]
            titles = [re.sub(r'^(?:Out for delivery|Dispatched|Ordered):\s*','',x.strip(),flags=re.I)
                      for x in re.findall(r'^\[ \] (.+)$',section,re.M)]
            if len(titles) != len(set(x.casefold() for x in titles)):
                warnings.append({'page':name,'message':'Possible duplicate delivery titles. Check the parcels before confirming receipt; separate parcels can share a title.'})
    now = datetime.now(timezone.utc)
    for name,row in (freshness or {}).items():
        status = str(row.get('status',''))
        if status in {'unavailable','partial'} or status.startswith('cached'):
            warnings.append({'page':'sources','message':f'{name}: {status}. Review its source date before relying on it.'})
        try:
            stamp = datetime.fromisoformat(row.get('source_checked_at') or row['checked_at'])
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
            if (now-stamp).total_seconds() > 86400:
                warnings.append({'page':'sources','message':f'{name} was checked more than 24 hours ago.'})
        except (ValueError,TypeError,KeyError): pass
    return warnings
