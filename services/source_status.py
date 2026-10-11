"""Canonical source states shared by collection, receipts, health and the web UI."""
from enum import StrEnum


class SourceState(StrEnum):
    FRESH='fresh'
    CACHED='cached'
    PARTIAL='partial'
    UNAVAILABLE='unavailable'
    DISABLED='disabled'


def state(value):
    value=str(value or '').strip().lower()
    if 'disabled' in value or 'excluded' in value: return SourceState.DISABLED
    if 'cached' in value: return SourceState.CACHED
    if value in {'partial','degraded'}: return SourceState.PARTIAL
    if value in {'fresh','checked','available','ok','healthy','loaded','complete'}: return SourceState.FRESH
    return SourceState.UNAVAILABLE


def label(value):
    result=state(value)
    if result==SourceState.CACHED and 'error' in str(value).lower(): return 'Cached after a failed refresh'
    return {SourceState.FRESH:'Fresh',SourceState.CACHED:'Cached',SourceState.PARTIAL:'Partial',
            SourceState.UNAVAILABLE:'Unavailable',SourceState.DISABLED:'Disabled by choice'}[result]


def health(value):
    result=state(value)
    return 'healthy' if result==SourceState.FRESH else 'degraded' if result in {SourceState.CACHED,SourceState.PARTIAL,SourceState.DISABLED} else 'failed'
