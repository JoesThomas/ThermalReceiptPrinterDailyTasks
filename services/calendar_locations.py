"""Private display/receipt location corrections; the external calendar is untouched."""
import fcntl
import hashlib
import json
import re
from pathlib import Path
from storage import write_json
FILE=Path(__file__).resolve().parents[1]/'data'/'calendar_location_overrides.json'


def identity(event):
    return hashlib.sha256('|'.join(str(event.get(k,'')) for k in ('uid','date','time','title')).encode()).hexdigest()


def validate(value):
    if not isinstance(value,dict) or len(value)>1000: raise ValueError('Invalid calendar location corrections.')
    for key,location in value.items():
        if not re.fullmatch(r'[a-f0-9]{64}',key) or not isinstance(location,str) or len(location)>500 or any(ord(c)<32 for c in location): raise ValueError('Invalid calendar location correction.')


def load():
    if not FILE.exists(): return {}
    result=json.loads(FILE.read_text());validate(result);return result


def save(key,location=None):
    if not re.fullmatch(r'[a-f0-9]{64}',key): raise ValueError('Invalid event.')
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        value=load()
        if location is None: value.pop(key,None)
        else: value[key]=location.strip()
        validate(value);write_json(FILE,value)


def apply(events):
    value=load();result=[]
    for event in events:
        row=dict(event);key=identity(row)
        row.update(correction_id=key,original_location=row.get('location',''),location_corrected=key in value)
        if key in value: row['location']=value[key]
        result.append(row)
    return result
