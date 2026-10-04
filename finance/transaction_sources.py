"""Private transaction collection scope, separate from cash balance selection."""
import json
from pathlib import Path
from storage import write_json
FILE=Path(__file__).resolve().parents[1]/'data'/'transaction_sources.json'


def validate(value):
    if not isinstance(value,dict) or value.get('monzo','first') not in {'first','all'} or set(value)-{'monzo'}:
        raise ValueError('Choose first Monzo account or all accounts.')


def load():
    from storage import PrivateStore
    value=PrivateStore(FILE,default=lambda:{'monzo':'first'},validate=validate).read()
    return {'monzo':'first',**value}


def save(mode):
    value={'monzo':mode};validate(value);write_json(FILE,value)


def select(provider,ids,settings=None):
    mode=(settings if settings is not None else load())['monzo']
    return ids[:1] if provider=='MONZO' and mode=='first' else ids
