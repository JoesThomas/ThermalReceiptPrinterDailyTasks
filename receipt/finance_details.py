"""Show changed/monthly finance detail; previews and failed sends do not consume it."""
from pathlib import Path
from datetime import date
import hashlib
import json
import re
from storage import PrivateStore

FILE=Path(__file__).resolve().parents[1]/'data'/'finance_details.json'
_PENDING={}


def validate(value):
    if not isinstance(value,dict) or set(value)-{'tax','assets'}:raise ValueError('Invalid finance detail state')
    for row in value.values():
        if not isinstance(row,dict) or not re.fullmatch(r'[a-f0-9]{64}',row.get('signature','')):raise ValueError('Invalid finance detail signature')
        date.fromisoformat(row['month']+'-01')


def store():return PrivateStore(FILE,default=dict,validate=validate)
def reset():_PENDING.clear()


def show(kind,payload,today):
    if kind not in ('tax','assets'):raise ValueError('Invalid finance detail kind')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    row={'signature':digest,'month':today.strftime('%Y-%m')}
    _PENDING[kind]=row
    try:previous=store().read().get(kind)
    except (ValueError,OSError):previous=None
    return previous!=row


def commit():
    if _PENDING:
        pending=dict(_PENDING)
        store().update(lambda value:value.update(pending))
        reset()
