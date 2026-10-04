"""User-confirmed collection and send status for saved receipts."""
import fcntl
import json
import re
from datetime import datetime,timezone
from pathlib import Path
from storage import write_json
FILE=Path(__file__).resolve().parents[1]/'data'/'receipt_recovery.json'


def read():
    try:
        value=json.loads(FILE.read_text())
        validate(value)
        return value
    except (ValueError,TypeError,OSError): return {}


def validate(value):
    if not isinstance(value,dict) or len(value)>5000: raise ValueError('Invalid receipt collection records.')
    for key,row in value.items():
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}',key) or not isinstance(row,dict): raise ValueError('Invalid receipt collection record.')
        for field in ('sent_at','collected_at'):
            if row.get(field): datetime.fromisoformat(row[field])


def mark(identifier,field,enabled=True):
    if field not in {'sent_at','collected_at'}: raise ValueError('Invalid receipt status.')
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        value=read();row=value.setdefault(identifier,{})
        row[field]=datetime.now(timezone.utc).isoformat() if enabled else None
        if len(value)>5000:
            value=dict(list(value.items())[-5000:])
        validate(value);write_json(FILE,value)


def status(identifier,source):
    row=read().get(identifier,{})
    return 'Collected (confirmed by you)' if row.get('collected_at') else 'Sent to printer (collection unconfirmed)' if source=='printed' or row.get('sent_at') else 'Generated (not confirmed sent)'
