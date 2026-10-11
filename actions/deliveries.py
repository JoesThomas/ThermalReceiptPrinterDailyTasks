from __future__ import annotations
import re
from datetime import date, datetime, timedelta

CARRIERS = {
    "royal mail": "ROYAL MAIL",
    "amazon": "AMAZON",
    "dpd": "DPD",
    "evri": "EVRI",
    "hermes": "EVRI",
    "dhl": "DHL",
    "ups": "UPS",
    "fedex": "FEDEX",
    "yodel": "YODEL",
    "parcelforce": "PARCELFORCE",
}

def carrier_from_text(text: str) -> str:
    low = text.lower()
    for needle, name in CARRIERS.items():
        if needle in low:
            return name
    return "DELIVERY"

def parse_time_window(text: str):
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(?:-|–|to)\s*([01]?\d|2[0-3]):([0-5]\d)\b", text, re.I)
    if not m:
        return None, None
    return f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}"

def compact_delivery(delivery: dict, today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    source = " ".join(str(delivery.get(k, "")) for k in ("carrier", "subject", "status", "body"))
    carrier = delivery.get("carrier") or carrier_from_text(source)
    start, end = parse_time_window(source)
    status = str(delivery.get("status", source)).lower()
    raw_date = delivery.get("delivery_date")
    d = None
    if raw_date:
        try:
            d = datetime.fromisoformat(str(raw_date)).date()
        except ValueError:
            pass
    if "delivered" in status:
        expected = "Delivered"
    elif start and end and (d is None or d == today):
        expected = f"Expected {start}-{end}"
    elif d == today or any(x in status for x in ("arriving today", "due today", "out for delivery")):
        expected = "Expected today"
    elif d == today + timedelta(days=1):
        expected = "Expected tomorrow"
    elif d:
        expected = f"Expected {d:%a %d %b}"
    else:
        expected = "Expected - time TBC"
    return str(carrier).upper(), expected
