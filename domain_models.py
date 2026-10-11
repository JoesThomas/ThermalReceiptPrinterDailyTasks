"""Normalised boundaries alongside legacy provider dictionaries."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TypedDict, NotRequired
from finance.money import parse


@dataclass(frozen=True)
class Transaction:
    date: date
    amount: Decimal
    merchant: str
    description: str

    @classmethod
    def from_mapping(cls, value):
        from finance_trends import _parse_date
        on=_parse_date(value);amount=parse(value.get('spend_amount',value.get('amount')))
        if on is None or amount is None: raise ValueError('Invalid transaction date or amount')
        merchant=str(value.get('merchant_name') or value.get('merchant') or value.get('description') or '').strip()
        return cls(on,amount,merchant,str(value.get('spend_description') or value.get('description') or merchant))


@dataclass(frozen=True)
class Commitment:
    name: str
    amount: Decimal
    due: date | None
    end: date | None

    @classmethod
    def from_mapping(cls,value):
        from finance.projection import day
        amount=parse(value.get('amount'))
        if amount is None or amount<0: raise ValueError('Invalid commitment amount')
        return cls(str(value.get('name') or 'Commitment'),amount,
                   day(value.get('next_payment') or value.get('due_date')),day(value.get('end_date')))


class DeliveryRecord(TypedDict):
    event_title: str
    carrier: str
    delivery_date: date
    time_from: str | None
    time_to: str | None
    order_ref: NotRequired[str]
    tracking_ref: NotRequired[str]
    notice_id: NotRequired[str]


@dataclass(frozen=True)
class SourceObservation:
    name: str
    status: str
    checked_at: str

    @property
    def state(self):
        from services.source_status import state
        return state(self.status)
