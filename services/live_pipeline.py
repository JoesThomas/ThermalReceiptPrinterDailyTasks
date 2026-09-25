"""Live receipt pipeline migrated from the former legacy_main entrypoint.
This module is invoked by app.py; it is no longer an application entrypoint.
"""
from services.vehicle_status import (
    get_vehicle_status,
    expiring_vehicle_items,
)
from services.subscriptions import (
    update_subscriptions_from_transactions,
)
import email
import imaplib
import traceback
from pathlib import Path
import json
from html import unescape
import calendar
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

"""
VINTAGE 1980s DAILY INFORMATION RECEIPT
NetumScan 80mm ESC/POS thermal printer

Contents:
- Date and time
- Today's Google Calendar events via iCal
- Full text of Google Doc #1
- Five random lines from Google Doc #2
- Stirchley, Birmingham weather
- Weather every 2 hours: temperature, humidity, wind and condition
- Compact black-bar temperature graph
- Daily weather summary
- Top 5 UK news headlines for the day
- Top 5 Birmingham news headlines for the day
- Automatic paper cut

Install:
    pip install python-escpos requests icalendar recurring-ical-events pillow
"""

from datetime import datetime, timedelta, date, time
import os
from io import BytesIO
import random
import re
import xml.etree.ElementTree as ET
import unicodedata
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont
from icalendar import Calendar
import recurring_ical_events
from escpos.printer import Usb
import meal_planner as meals
from calendar_travel import (
    travel_options,
    sensible_chained_origin,
    clear_route_cache,
)

from finance.receipt import (
    print_integrated_finance,
)

from receipt_settings import (
    load_receipt_settings,
    feature_enabled,
    display_value,
    one_shot_requested,
    consume_one_shot,
    finance_requested,
    food_shop_requested,
    shopping_list_requested,
)

from routines import (
    due_routines,
)

from services.villa import (
    get_aston_villa_match_today,
    print_villa_matchday,
)

# ============================================================
# PRIVATE CONFIGURATION
# ============================================================

# services/live_pipeline.py

from pathlib import Path

# live_pipeline.py is inside /services, so the project root is its parent.
BASE_DIR = Path(__file__).resolve().parent.parent

PASSWORDS_FILE = BASE_DIR / "passwords.json"

SUBSCRIPTIONS_FILE = (
    BASE_DIR
    / "data"
    / "subscriptions.json"
)

# ============================================================
# ROUTE CACHE
# ============================================================

_ROUTE_CACHE = {}


def clear_route_cache():
    """
    Clear cached Google Routes responses.

    Called once at the start of each receipt run so duplicate
    route requests within the same run can reuse results without
    carrying stale journey data into the next run.
    """
    _ROUTE_CACHE.clear()

def load_private_config():
    """
    Load private URLs, API credentials and tokens from passwords.json.

    Keep passwords.json out of source control.
    """
    if not PASSWORDS_FILE.exists():
        raise RuntimeError(
            f"Missing private configuration file: {PASSWORDS_FILE}"
        )

    try:
        with PASSWORDS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Invalid JSON in {PASSWORDS_FILE}: {error}"
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError("passwords.json must contain a JSON object.")

    return data


PRIVATE = load_private_config()

vehicles = PRIVATE.get(
    "vehicles",
    [],
)

dvla_api_key = (
    PRIVATE
    .get("dvla", {})
    .get("api_key", "")
)

def private_value(section, key, default=""):
    section_data = PRIVATE.get(section, {})
    if not isinstance(section_data, dict):
        return default
    return section_data.get(key, default)


# ============================================================
# CONFIGURATION
# ============================================================

# Replace with your printer's actual USB IDs.
PRINTER_VENDOR_ID = 0x0416
PRINTER_PRODUCT_ID = 0x5011

LOCAL_NEWS_QUERIES = (
    (
        '"Birmingham" '
        '"West Midlands" '
        'council OR transport OR development '
        'OR business OR events'
    ),
    (
        '"Birmingham" '
        'road OR train OR bus OR tram '
        'OR disruption OR closure'
    ),
    (
        '"Birmingham city centre" '
        'development OR planning OR opening '
        'OR closing OR regeneration'
    ),
    (
        '"Birmingham" '
        'festival OR event OR weekend'
    ),
    (
        '"Aston Villa" '
        'confirmed OR signs OR injury '
        'OR fixture OR statement'
    ),
)

# -------------------------------------------------
# BIRMINGHAM NEWS PRIORITISATION
# -------------------------------------------------

LOCAL_NEWS_MIN_SCORE = 4


BIRMINGHAM_UK_SIGNALS = (
    "birmingham city council",
    "west midlands",
    "west midlands railway",
    "west midlands police",
    "transport for west midlands",
    "birmingham new street",
    "birmingham airport",
    "bullring",
    "grand central",
    "digbeth",
    "edgbaston",
    "selly oak",
    "stirchley",
    "bournville",
    "moseley",
    "jewellery quarter",
    "aston",
    "longbridge",
    "solihull",
    "sandwell",
)


NON_UK_BIRMINGHAM_SIGNALS = (
    "birmingham, al",
    "birmingham alabama",
    "alabama",
    "al.com",
    "birmingham, mi",
    "birmingham michigan",
    "michigan",
)


HIGH_VALUE_LOCAL_SIGNALS = (
    # Transport
    "road closed",
    "road closure",
    "roadworks",
    "traffic",
    "train service",
    "rail service",
    "bus service",
    "tram service",
    "service suspended",
    "service disruption",
    "travel disruption",
    "new street",
    "west midlands railway",
    "transport for west midlands",

    # Council / public services
    "birmingham city council",
    "council",
    "bin collection",
    "waste collection",
    "public transport",
    "nhs",
    "hospital",

    # Development / business
    "planning permission",
    "planning application",
    "redevelopment",
    "development",
    "regeneration",
    "new homes",
    "city centre",
    "opening",
    "closing",
    "jobs",
)

EVENT_SIGNALS = (
    "festival",
    "event",
    "concert",
    "exhibition",
    "show",
    "market",
    "fair",
)

LOW_VALUE_NEWS_SIGNALS = (
    "match report",
    "player ratings",
    "predicted line-up",
    "predicted lineup",
    "starting xi",
    "transfer rumour",
    "transfer rumor",
    "transfer gossip",
    "should emery",
    "could emery",
    "must emery",
    "emery should",
    "emery could",
    "blunder",
    "embarrassing",
    "dream signing",
    "ideal signing",
    "urged to",
    "told to",
    "pundit says",
    "what emery said",
    "what happened",
    "three wins in three",
)


IMPORTANT_VILLA_SIGNALS = (
    "signs",
    "signed",
    "signing",
    "joins",
    "joined",
    "leaves",
    "departure",
    "injury",
    "injured",
    "fixture changed",
    "fixture postponed",
    "postponed",
    "manager appointed",
    "manager sacked",
    "club statement",
    "confirmed",
    "drawn against",
)

IMMEDIATE_LOCAL_SIGNALS = (
    "major disruption",
    "severe disruption",
    "service suspended",
    "services suspended",
    "broken down train",
    "train cancelled",
    "trains cancelled",
    "road closed",
    "road closure",
    "emergency closure",
    "tram suspended",
    "bus disruption",
    "flood warning",
)

# Google Calendar "Secret address in iCal format".
CALENDAR_ICAL_URL = private_value("calendar", "ical_url")

# Google Docs URLs. The documents must be accessible without login.
GOOGLE_DOC_1_URL = private_value("google_docs", "todo_url")
GOOGLE_DOC_2_URL = private_value("google_docs", "random_url")
SUBSCRIPTIONS_GOOGLE_DOC_URL = private_value("google_docs", "subscriptions_url")
FOOD_SHOP_GOOGLE_DOC_URL = private_value("google_docs", "food_shop_url")
TRANSPORT_API_APP_ID = private_value("transport_api", "app_id")
TRANSPORT_API_APP_KEY = private_value("transport_api", "app_key")
BOURNVILLE_CRS = "BRV"
ASTON_CRS = "AST"
FOOTBALL_DATA_API_KEY = private_value("football", "api_key")
ASTON_VILLA_TEAM_ID = 58
MATCH_TRAIN_WINDOW_HOURS = 2
MATCH_ARRIVAL_BUFFER_MINUTES = 30

# Stirchley, Birmingham.
LATITUDE = 52.4294
LONGITUDE = -1.92035
LOCATION_NAME = "STIRCHLEY"
LOCATION_REGION = "BIRMINGHAM, UK"

# Compact 80mm receipt width.
RECEIPT_WIDTH = 42

# Number of random lines from Google Doc #2.
RANDOM_LINES = 5

def cut_receipt_section(printer):
    """
    Finish the current receipt section and cut the paper.
    """
    printer.text("\n\n\n")

    try:
        printer.cut()
    except Exception as error:
        print(
            "Receipt cut error:",
            repr(error),
        )

# File containing the shopping list.
# ============================================================
# GMAIL DELIVERY SOURCE - IMAP + APP PASSWORD
# ============================================================

def _decode_email_header(value):
    if not value:
        return ""
    try:
        decoded_parts = email.header.decode_header(value)
    except Exception:
        return value
    output = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            output.append(
                part.decode(
                    charset or "utf-8",
                    errors="replace",
                )
            )
        else:
            output.append(part)
    return "".join(output)

def _html_to_plain_text(html_text):
    if not html_text:
        return ""
    text = re.sub(
        r"<script.*?</script>",
        " ",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<style.*?</style>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<br\\s*/?>",
        "\\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"</p>",
        "\\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = unescape(text)

    text = re.sub(
        r"[ \\t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\\n\\s*\\n+",
        "\\n",
        text,
    )

    return text.strip()

def _extract_imap_message_body(message):
    plain_parts = []
    html_parts = []

    parts = message.walk() if message.is_multipart() else [message]

    for part in parts:
        content_type = part.get_content_type()
        disposition = str(
            part.get("Content-Disposition", "")
        ).lower()

        if "attachment" in disposition:
            continue

        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None

        if not payload:
            continue

        charset = part.get_content_charset() or "utf-8"

        try:
            text = payload.decode(
                charset,
                errors="replace",
            )
        except Exception:
            text = payload.decode(
                "utf-8",
                errors="replace",
            )

        if content_type == "text/plain":
            plain_parts.append(text)
        elif content_type == "text/html":
            html_parts.append(
                _html_to_plain_text(text)
            )

    if plain_parts:
        return "\n".join(plain_parts)

    if html_parts:
        return "\n".join(html_parts)

    return ""


def _likely_delivery_email(subject, body):
    text = f"{subject} {body}".lower()

    score = 0

    strong_delivery_terms = (
        "out for delivery",
        "due for delivery",
        "delivery expected",
        "will be delivered",
        "has been delivered",
        "arriving today",
        "arriving tomorrow",
        "your parcel",
        "your package",
        "track your parcel",
        "track your package",
        "tracking number",
        "dispatched",
        "despatched",
        "shipped",
        "on its way",
    )

    courier_terms = (
        "royal mail",
        "dpd",
        "evri",
        "yodel",
        "dhl",
        "fedex",
        "ups",
        "amazon logistics",
        "parcelforce",
    )

    general_terms = (
        "delivery",
        "parcel",
        "package",
        "tracking",
        "courier",
        "arriving",
        "delivered",
        "dispatch",
        "shipment",
    )

    marketing_terms = (
        "save £",
        "save gbp",
        "discount",
        "voucher",
        "promo",
        "promotion",
        "first grocery shop",
        "shop now",
        "special offer",
        "newsletter",
    )

    for term in strong_delivery_terms:
        if term in text:
            score += 3

    for term in courier_terms:
        if term in text:
            score += 2

    for term in general_terms:
        if term in text:
            score += 1

    for term in marketing_terms:
        if term in text:
            score -= 4

    return score >= 2


def get_gmail_delivery_emails():
    """
    Read recent Gmail messages via IMAP using a Google App
    Password. The login details are read only from environment
    variables and are never written to this script.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print(
            "Gmail IMAP credentials not configured; "
            "using delivery JSON fallback."
        )
        return []

    mailbox = None

    try:
        mailbox = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST)

        mailbox.login(
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD,
        )

        status, _ = mailbox.select(
            "INBOX",
            readonly=True,
        )

        if status != "OK":
            print("Could not open Gmail inbox.")
            return []

        since_date = (
            datetime.now(
                ZoneInfo("Europe/London")
            ).date()
            - timedelta(days=GMAIL_SEARCH_DAYS)
        )

        status, data = mailbox.search(
            None,
            "SINCE",
            since_date.strftime("%d-%b-%Y"),
        )

        if status != "OK" or not data:
            return []

        message_ids = data[0].split()
        message_ids = message_ids[-GMAIL_MAX_MESSAGES:][::-1]

        records = []

        for message_id in message_ids:
            status, message_data = mailbox.fetch(
                message_id,
                "(RFC822)",
            )

            if status != "OK":
                continue

            raw_message = None

            for item in message_data:
                if isinstance(item, tuple) and len(item) > 1:
                    raw_message = item[1]
                    break

            if not raw_message:
                continue

            try:
                parsed_message = email.message_from_bytes(
                    raw_message
                )
            except Exception:
                continue

            subject = _decode_email_header(
                parsed_message.get("Subject", "")
            )

            body = _extract_imap_message_body(
                parsed_message
            )

            is_delivery = _likely_delivery_email(
                subject,
                body,
            )

            if not is_delivery:
                continue

            records.append({
                "email_subject": subject,
                "email_body": body,
            })

        return records

    except imaplib.IMAP4.error as error:
        print(
            "Gmail IMAP login/search failed:",
            error,
        )
        return []

    except OSError as error:
        print(
            "Could not connect to Gmail IMAP:",
            error,
        )
        return []

    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except Exception:
                pass

def _transportapi_bournville_departures(
    start_time,
):
    url = (
        "https://transportapi.com/v3/uk/train/"
        f"station/{BOURNVILLE_CRS}/"
        f"{start_time.strftime('%Y-%m-%d')}/"
        f"{start_time.strftime('%H:%M')}/"
        "timetable.json"
    )

    response = requests.get(
        url,
        params={
            "app_id": TRANSPORT_API_APP_ID,
            "app_key": TRANSPORT_API_APP_KEY,
            "calling_at": ASTON_CRS,
            "train_status": "passenger",
        },
        timeout=20,
    )

    response.raise_for_status()

    return (
        response.json()
        .get("departures", {})
        .get("all", [])
    )

def _rail_time(
    date_value,
    time_text,
):
    if not time_text:
        return None

    try:
        parsed_time = datetime.strptime(
            time_text,
            "%H:%M",
        ).time()

        return datetime.combine(
            date_value,
            parsed_time,
            tzinfo=ZoneInfo(
                "Europe/London"
            ),
        )

    except ValueError:
        return None

# ============================================================
# UPCOMING DELIVERIES
# ============================================================

def _parse_delivery_date(date_text):
    """
    Parse common UK and ISO delivery-date formats.

    UK-style DD/MM/YYYY is deliberately tried before US-style
    MM/DD/YYYY because this receipt project is UK based.
    """
    if not date_text:
        return None

    date_text = date_text.strip()

    formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                date_text,
                fmt
            ).date()
        except ValueError:
            continue

    return None

def _normalise_delivery_time(value):
    """
    Convert common delivery-time formats to HH:MM.

    Examples:
        14:30     -> 14:30
        2:30 PM   -> 14:30
        4:30 pm   -> 16:30
    """
    if not value:
        return None

    value = (
        str(value)
        .strip()
        .upper()
        .replace(".", "")
    )

    # Normalise spacing:
    # "2:30PM" -> "2:30 PM"
    value = re.sub(
        r"(\d)(AM|PM)$",
        r"\1 \2",
        value,
    )

    for fmt in (
        "%H:%M",
        "%I:%M %p",
        "%I %p",
    ):
        try:
            return (
                datetime.strptime(
                    value,
                    fmt,
                )
                .strftime("%H:%M")
            )

        except ValueError:
            continue

    return None

def extract_delivery_from_email(
    email_subject,
    email_body
):
    email_subject = (
        email_subject
        or ""
    )

    email_body = (
        email_body
        or ""
    )

    full_text = (
        email_subject
        + " "
        + email_body
    )

    lower_text = (
        full_text.lower()
    )

    # -------------------------------------------------
    # ALREADY DELIVERED
    # -------------------------------------------------
    #
    # A completed delivery must never be returned as an
    # upcoming delivery, even if the email also contains
    # phrases such as "delivery today".
    #

    delivered_patterns = (
        r"\bhas been delivered\b",
        r"\bwas delivered\b",
        r"\bwe(?:'ve| have) delivered\b",
        r"\bparcel delivered\b",
        r"\bpackage delivered\b",
        r"\bdelivered successfully\b",
        r"\bdelivered to\b",
        r"\bproof of delivery\b",
    )

    if any(
            re.search(
                pattern,
                lower_text,
            )
            for pattern in delivered_patterns
    ):
        return None

    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    # -------------------------
    # CARRIER
    # -------------------------

    carrier = None

    carrier_patterns = (
        ("EVRI", (
            "evri",
            "myhermes",
            "hermes parcel",
        )),
        ("ROYAL MAIL", (
            "royal mail",
        )),
        ("AMAZON", (
            "amazon",
        )),
        ("DPD", (
            "dpd",
        )),
        ("DHL", (
            "dhl",
        )),
        ("YODEL", (
            "yodel",
        )),
        ("PARCELFORCE", (
            "parcelforce",
        )),
        ("UPS", (
            "ups",
            "united parcel service",
        )),
        ("FEDEX", (
            "fedex",
            "federal express",
        )),
    )

    for carrier_name, identifiers in carrier_patterns:
        if any(
            identifier in lower_text
            for identifier in identifiers
        ):
            carrier = carrier_name
            break

    # -------------------------
    # DELIVERY DATE
    # -------------------------

    delivery_date = None

    # -------------------------
    # EXPLICIT WEEKDAY
    # -------------------------
    #
    # Check this first.
    #
    # This is particularly important for Amazon emails.
    # Their progress tracker can contain text such as:
    #
    # Ordered
    # Dispatched
    # Out for delivery
    # Delivered
    #
    # even though the actual delivery statement says:
    #
    # Arriving Saturday
    #
    # An explicit arrival weekday therefore takes
    # precedence over generic delivery-status wording.
    # -------------------------

    weekday_match = re.search(
        r"\b(?:arriving|arrives|expected|due)"
        r"\s+(?:on\s+)?"
        r"(monday|tuesday|wednesday|thursday|"
        r"friday|saturday|sunday)\b",
        lower_text,
        flags=re.IGNORECASE,
    )

    if weekday_match:
        weekday_name = (
            weekday_match
            .group(1)
            .lower()
        )

        weekday_numbers = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }

        target_weekday = (
            weekday_numbers[
                weekday_name
            ]
        )

        days_ahead = (
                             target_weekday
                             - today.weekday()
                     ) % 7

        delivery_date = (
                today
                + timedelta(
            days=days_ahead
        )
        )

    # -------------------------
    # TODAY
    # -------------------------

    if not delivery_date:

        today_patterns = (
            r"\b(?:arriving|arrives|expected|due)"
            r"\s+(?:on\s+)?today\b",

            r"\bdelivery\s+(?:is\s+)?"
            r"(?:expected\s+)?today\b",

            r"\bparcel\b.{0,40}"
            r"\b(?:arriving|due|expected)\s+today\b",

            r"\bpackage\b.{0,40}"
            r"\b(?:arriving|due|expected)\s+today\b",
        )

        if any(
                re.search(
                    pattern,
                    lower_text,
                    flags=re.IGNORECASE,
                )
                for pattern in today_patterns
        ):
            delivery_date = today

    # -------------------------
    # TOMORROW
    # -------------------------

    if not delivery_date:

        tomorrow_patterns = (
            r"\b(?:arriving|arrives|expected|due)"
            r"\s+(?:on\s+)?tomorrow\b",

            r"\bdelivery\s+(?:is\s+)?"
            r"(?:expected\s+)?tomorrow\b",

            r"\bparcel\b.{0,40}"
            r"\b(?:arriving|due|expected)\s+tomorrow\b",

            r"\bpackage\b.{0,40}"
            r"\b(?:arriving|due|expected)\s+tomorrow\b",
        )

        if any(
                re.search(
                    pattern,
                    lower_text,
                    flags=re.IGNORECASE,
                )
                for pattern in tomorrow_patterns
        ):
            delivery_date = (
                    today
                    + timedelta(days=1)
            )

    # -------------------------
    # WEEKDAY DELIVERY
    # -------------------------

    if not delivery_date:
        weekday_match = re.search(
            r"\b(?:arriv\w*|delivery|expected)"
            r".{0,20}?\b"
            r"(monday|tuesday|wednesday|thursday|"
            r"friday|saturday|sunday)\b",
            lower_text,
            flags=re.IGNORECASE,
        )

        if weekday_match:
            weekday_name = (
                weekday_match.group(1).lower()
            )

            weekday_numbers = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }

            target_weekday = (
                weekday_numbers[
                    weekday_name
                ]
            )

            days_ahead = (
                                 target_weekday
                                 - today.weekday()
                         ) % 7

            delivery_date = (
                    today
                    + timedelta(
                days=days_ahead
            )
            )

    # -------------------------
    # NUMERIC DATES
    # -------------------------

    if not delivery_date:
        date_patterns = [
            (
                r"(?:delivery|arrives?|"
                r"arriving|delivering|"
                r"delivered on|"
                r"expected|eta|due)"
                r"[\s:,-]*"
                r"(\d{1,2}[-/]"
                r"\d{1,2}[-/]"
                r"\d{2,4})"
            ),
            (
                r"(\d{1,2}[-/]"
                r"\d{1,2}[-/]"
                r"\d{2,4})"
                r"(?:\s+"
                r"(?:delivery|arrives?|"
                r"arriving|delivering|"
                r"delivered))"
            ),
            (
                r"(?:delivery|arrives?|"
                r"arriving|delivering|"
                r"expected|due)"
                r"[\s:,-]*"
                r"(\d{4}-\d{2}-\d{2})"
            ),
        ]

        for pattern in date_patterns:
            match = re.search(
                pattern,
                full_text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            delivery_date = (
                _parse_delivery_date(
                    match.group(1)
                )
            )

            if delivery_date:
                break

    # -------------------------
    # UK TEXT DATES
    # -------------------------

    if not delivery_date:
        text_date_pattern = (
            r"(?:delivery|arrives?|"
            r"arriving|delivering|"
            r"delivered on|"
            r"expected|due)"
            r".{0,40}?"
            r"(\d{1,2})"
            r"(?:st|nd|rd|th)?"
            r"\s+"
            r"(jan(?:uary)?|"
            r"feb(?:ruary)?|"
            r"mar(?:ch)?|"
            r"apr(?:il)?|"
            r"may|"
            r"jun(?:e)?|"
            r"jul(?:y)?|"
            r"aug(?:ust)?|"
            r"sep(?:tember)?|"
            r"oct(?:ober)?|"
            r"nov(?:ember)?|"
            r"dec(?:ember)?)"
            r"(?:\s+(\d{4}))?"
        )

        match = re.search(
            text_date_pattern,
            full_text,
            flags=re.IGNORECASE,
        )

        if match:
            day = int(
                match.group(1)
            )

            month_text = (
                match.group(2)
            )

            year = int(
                match.group(3)
                or today.year
            )

            for fmt in (
                "%d %B %Y",
                "%d %b %Y",
            ):
                try:
                    delivery_date = (
                        datetime.strptime(
                            (
                                f"{day} "
                                f"{month_text} "
                                f"{year}"
                            ),
                            fmt,
                        ).date()
                    )

                    break

                except ValueError:
                    pass

            # If we've crossed New Year and the parsed
            # month/day is already well in the past,
            # assume the next calendar year.
            if (
                delivery_date
                and delivery_date
                < today - timedelta(days=30)
            ):
                try:
                    delivery_date = (
                        delivery_date.replace(
                            year=(
                                delivery_date.year
                                + 1
                            )
                        )
                    )
                except ValueError:
                    pass

    # -------------------------
    # NO DELIVERY DATE
    # -------------------------

    if not delivery_date:
        return None

    # -------------------------
    # DELIVERY TIME WINDOW
    # -------------------------

    time_from = None
    time_to = None

    time_patterns = (
        # 14:30 - 16:30
        (
            r"\b"
            r"(\d{1,2}:\d{2})"
            r"\s*[-–—]\s*"
            r"(\d{1,2}:\d{2})"
            r"\b"
        ),

        # between 14:30 and 16:30
        (
            r"\bbetween\s+"
            r"(\d{1,2}:\d{2})"
            r"\s+and\s+"
            r"(\d{1,2}:\d{2})"
            r"\b"
        ),

        # 2:30 PM - 4:30 PM
        (
            r"\b"
            r"(\d{1,2}:\d{2}\s*[ap]\.?m\.?)"
            r"\s*[-–—]\s*"
            r"(\d{1,2}:\d{2}\s*[ap]\.?m\.?)"
            r"\b"
        ),

        # between 2:30 PM and 4:30 PM
        (
            r"\bbetween\s+"
            r"(\d{1,2}:\d{2}\s*[ap]\.?m\.?)"
            r"\s+and\s+"
            r"(\d{1,2}:\d{2}\s*[ap]\.?m\.?)"
            r"\b"
        ),
    )

    for pattern in time_patterns:
        match = re.search(
            pattern,
            full_text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        time_from = (
            _normalise_delivery_time(
                match.group(1)
            )
        )

        time_to = (
            _normalise_delivery_time(
                match.group(2)
            )
        )

        if time_from and time_to:
            break

    # -------------------------
    # EVENT TITLE
    # -------------------------

    event_title = (
        email_subject.strip()
    )

    if len(event_title) < 3:
        if carrier:
            event_title = (
                f"{carrier} Delivery"
            )
        else:
            event_title = (
                "Package Delivery"
            )

    # -------------------------
    # RESULT
    # -------------------------

    return {
        "event_title": (
            printer_safe_text(
                event_title
            )
        ),
        "carrier": carrier,
        "delivery_date": (
            delivery_date
        ),
    }

def get_upcoming_deliveries():
    """
    Read likely delivery emails from Gmail, extract delivery
    dates, and return upcoming parcels.

    If Gmail is unavailable, delivery_emails.json remains a
    fallback source for testing/offline use.
    """
    email_records = get_gmail_delivery_emails()

    # -------------------------------------------------
    # FALLBACK JSON
    # -------------------------------------------------

    if (
        not email_records
        and DELIVERY_EMAIL_FILE.exists()
    ):
        try:
            fallback_records = json.loads(
                DELIVERY_EMAIL_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if isinstance(
                fallback_records,
                list,
            ):
                email_records = fallback_records

        except (
            OSError,
            json.JSONDecodeError,
        ):
            pass

    if not email_records:
        return []

    # -------------------------------------------------
    # DATE WINDOW
    # -------------------------------------------------

    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    latest = (
        today
        + timedelta(
            days=DELIVERY_LOOKAHEAD_DAYS
        )
    )

    deliveries = []
    seen = set()

    # -------------------------------------------------
    # PROCESS EMAILS
    # -------------------------------------------------

    for record in email_records:

        if not isinstance(
            record,
            dict,
        ):
            continue

        # IMPORTANT:
        # Define these before trying to use them.
        subject = (
            record.get(
                "email_subject",
                "",
            )
            or ""
        )

        body = (
            record.get(
                "email_body",
                "",
            )
            or ""
        )

        # -------------------------------------------------
        # IS THIS ACTUALLY DELIVERY RELATED?
        # -------------------------------------------------

        if not _likely_delivery_email(
            subject,
            body,
        ):
            continue

        # -------------------------------------------------
        # EXTRACT DELIVERY DATE
        # -------------------------------------------------

        delivery = extract_delivery_from_email(
            subject,
            body,
        )

        # -------------------------------------------------
        # TEMPORARY EVRI DEBUGGING
        # -------------------------------------------------

        if "evri" in (
            subject + " " + body
        ).lower():

            print(
                "\n=== EVRI DELIVERY DEBUG ==="
            )

            print(
                "SUBJECT:",
                repr(subject),
            )

            print(
                "PARSED:",
                repr(delivery),
            )

            if delivery:
                print(
                    "PARSED DATE:",
                    delivery.get(
                        "delivery_date"
                    ),
                )

            print(
                "TODAY:",
                today,
            )

            print(
                "===========================\n"
            )

        # -------------------------------------------------
        # NOTHING EXTRACTED
        # -------------------------------------------------

        if not delivery:
            continue

        delivery_date = delivery.get(
            "delivery_date"
        )

        if not delivery_date:
            continue

        # -------------------------------------------------
        # ONLY TODAY -> LOOKAHEAD WINDOW
        # -------------------------------------------------

        if not (
            today
            <= delivery_date
            <= latest
        ):
            continue

        # -------------------------------------------------
        # DEDUPLICATE
        # -------------------------------------------------

        key = (
            delivery["event_title"],
            delivery_date.isoformat(),
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        deliveries.append(
            delivery
        )

    # -------------------------------------------------
    # EARLIEST FIRST
    # -------------------------------------------------

    deliveries.sort(
        key=lambda item:
        item["delivery_date"]
    )

    return deliveries[
        :MAX_UPCOMING_DELIVERIES
    ]


def _delivery_value(delivery, *keys, default=None):
    """Return the first non-empty value from a delivery dictionary."""
    if not isinstance(delivery, dict):
        return default

    for key in keys:
        value = delivery.get(key)
        if value is not None and str(value).strip():
            return value

    return default


def _normalise_delivery_carrier(delivery):
    """
    Return a short carrier name.

    The current email parser stores the email subject as event_title,
    so this also recognises carrier names embedded in that subject.
    """
    carrier = _delivery_value(
        delivery,
        "carrier",
        "courier",
        "company",
        "provider",
        "delivery_company",
        "event_title",
        default="DELIVERY",
    )

    carrier_text = str(carrier).strip()
    lower = carrier_text.lower()

    carrier_names = (
        ("royal mail", "ROYAL MAIL"),
        ("royalmail", "ROYAL MAIL"),
        ("amazon logistics", "AMAZON"),
        ("amazon", "AMAZON"),
        ("dpd local", "DPD"),
        ("dpd", "DPD"),
        ("evri", "EVRI"),
        ("hermes", "EVRI"),
        ("parcelforce", "PARCELFORCE"),
        ("dhl", "DHL"),
        ("ups", "UPS"),
        ("fedex", "FEDEX"),
        ("yodel", "YODEL"),
    )

    for needle, clean_name in carrier_names:
        if needle in lower:
            return clean_name

    # Avoid printing a long email subject as the carrier.
    if len(carrier_text) > 24:
        return "DELIVERY"

    return printer_safe_text(carrier_text).upper()


def _parse_delivery_date(value):
    """Turn common date representations into a date object."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    value = str(value).strip()

    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except (ValueError, TypeError):
        return None


def _clean_delivery_time(value):
    """Return a compact 24-hour time where possible."""
    if value is None:
        return None

    value = str(value).strip()

    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            pass

    return printer_safe_text(value)


def format_delivery_expected(delivery):
    """
    Convert delivery data into one clean line, e.g.
    'Expected today' or 'Expected 13:00-16:00'.
    """
    if not isinstance(delivery, dict):
        return "Expected - time TBC"

    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    status = str(
        _delivery_value(
            delivery,
            "status",
            "delivery_status",
            "state",
            default="",
        )
    ).lower()

    if "delivered" in status:
        return "Delivered"

    raw_date = _delivery_value(
        delivery,
        "delivery_date",
        "date",
        "expected_date",
        "estimated_date",
        "eta_date",
    )
    delivery_date = _parse_delivery_date(raw_date)

    time_from = _clean_delivery_time(
        _delivery_value(
            delivery,
            "time_from",
            "from_time",
            "start_time",
            "window_start",
            "estimated_from",
        )
    )
    time_to = _clean_delivery_time(
        _delivery_value(
            delivery,
            "time_to",
            "to_time",
            "end_time",
            "window_end",
            "estimated_to",
        )
    )

    if delivery_date == today:
        if time_from and time_to:
            return f"Expected {time_from}-{time_to}"
        return "Expected today"

    if delivery_date == today + timedelta(days=1):
        if time_from and time_to:
            return f"Tomorrow {time_from}-{time_to}"
        return "Expected tomorrow"

    if delivery_date:
        days_away = (delivery_date - today).days
        if 2 <= days_away <= 6:
            return f"Expected {delivery_date.strftime('%A')}"
        return f"Expected {delivery_date.strftime('%d %b')}"

    today_phrases = (
        "out for delivery",
        "due today",
        "delivery today",
        "arriving today",
    )

    if any(phrase in status for phrase in today_phrases):
        if time_from and time_to:
            return f"Expected {time_from}-{time_to}"
        return "Expected today"

    if time_from and time_to:
        return f"Expected {time_from}-{time_to}"

    return "Expected - time TBC"


def print_upcoming_deliveries(printer, deliveries):
    """
    Print only useful delivery information.

    Example:
        ROYAL MAIL
        Expected today
        AMAZON
        Expected 13:00-16:00

    The entire section is omitted when there are no deliveries.
    """
    if not deliveries:
        return

    if isinstance(deliveries, dict):
        deliveries = [deliveries]

    deliveries = [
        item for item in deliveries
        if isinstance(item, dict)
    ]

    if not deliveries:
        return

    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, "UPCOMING DELIVERIES")
    printer.set(bold=False)
    print_line(printer, "-")

    for delivery in deliveries:
        left(
            printer,
            _normalise_delivery_carrier(delivery),
        )
        left(
            printer,
            format_delivery_expected(delivery),
        )


# ============================================================
# FINANCE CHECK - LIVE OPEN BANKING DATA
# ============================================================
# Finance is only fetched when "finance check" appears in the
# Google Doc / to-do text.
#
# TrueLayer Data API credentials:
TRUELAYER_CLIENT_ID = private_value("truelayer", "client_id")
TRUELAYER_CLIENT_SECRET = private_value("truelayer", "client_secret")

# One authorised refresh token per provider/account connection.
# These are obtained after authorising each bank through TrueLayer
# with accounts/cards + balance + offline_access permission.
TRUELAYER_HSBC_REFRESH_TOKEN = private_value("truelayer", "hsbc_refresh_token")
TRUELAYER_MONZO_REFRESH_TOKEN = private_value("truelayer", "monzo_refresh_token")
TRUELAYER_AMEX_REFRESH_TOKEN = private_value("truelayer", "amex_refresh_token")


TRUELAYER_AUTH_URL = "https://auth.truelayer.com/connect/token"
TRUELAYER_DATA_URL = "https://api.truelayer.com/data/v1"

# If TrueLayer rotates a refresh token, the script stores the latest
# token locally so scheduled Raspberry Pi runs keep working.
TRUELAYER_TOKEN_FILE = (
    Path.home() / ".thermal_receipt_truelayer_tokens.json"
)


# Finance analysis settings.
FINANCE_TRANSACTION_LOOKBACK_DAYS = 90
FINANCE_SUBSCRIPTION_MIN_OCCURRENCES = 2
FINANCE_SUBSCRIPTION_AMOUNT_TOLERANCE = 0.15
FINANCE_SUBSCRIPTION_MIN_DAYS = 20
FINANCE_SUBSCRIPTION_MAX_DAYS = 40

# Classifications treated as essential for survival-mode runway.
FINANCE_SALARY_KEYWORDS = (
    "salary",
    "payroll",
    "wages",
    "pay",
)

FINANCE_INTERNAL_TRANSFER_KEYWORDS = (
    "transfer",
    "internal transfer",
    "own account",
)

FINANCE_ESSENTIAL_KEYWORDS = (
    "housing",
    "rent",
    "mortgage",
    "utilities",
    "utility",
    "energy",
    "electric",
    "gas",
    "water",
    "council",
    "tax",
    "grocer",
    "food",
    "supermarket",
    "transport",
    "fuel",
    "petrol",
    "insurance",
    "health",
    "medical",
    "pharmacy",
    "phone",
    "mobile",
    "internet",
    "broadband",
)

def format_money(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0.0

    if value < 0:
        return f"-£{abs(value):,.2f}"

    return f"£{value:,.2f}"

# ============================================================
# UPCOMING DELIVERIES
# ============================================================
# Optional JSON file containing recent delivery-related emails.
# This keeps email credentials out of the printer script.
#
# Format:
# [
#   {"email_subject": "...", "email_body": "..."},
#   {"email_subject": "...", "email_body": "..."}
# ]
DELIVERY_EMAIL_FILE = Path("delivery_emails.json")
MAX_UPCOMING_DELIVERIES = 5
DELIVERY_LOOKAHEAD_DAYS = 14

# Gmail integration via IMAP + Google App Password.
#
# Set these in your terminal before running the script:
#   export GMAIL_ADDRESS="you@gmail.com"
#   export GMAIL_APP_PASSWORD="your_16_character_app_password"
#
# Do not put the App Password directly in this Python file.
GMAIL_ADDRESS = private_value("email", "address")
GMAIL_APP_PASSWORD = private_value("email", "app_password")
GMAIL_IMAP_HOST = private_value("email", "imap_host", "imap.gmail.com")
GMAIL_SEARCH_DAYS = 30
GMAIL_MAX_MESSAGES = 40

# Google News RSS feed for UK headlines.
NEWS_RSS_URL = (
    "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en"
)
NEWS_HEADLINES = 3
LOCAL_NEWS_HEADLINES = 3
LOCAL_NEWS_QUERY = "Birmingham"
LOCAL_NEWS_RSS_URL = (
    "https://news.google.com/rss/search"
)

# ============================================================
# WEATHER
# ============================================================

WEATHER_CODES = {
    0: "SUNNY",
    1: "MAINLY SUNNY",
    2: "PARTLY CLOUDY",
    3: "CLOUDY",
    45: "FOGGY",
    48: "FOGGY",
    51: "LIGHT DRIZZLE",
    53: "DRIZZLE",
    55: "HEAVY DRIZZLE",
    56: "FREEZING DRIZZLE",
    57: "FREEZING DRIZZLE",
    61: "LIGHT RAIN",
    63: "RAINY",
    65: "HEAVY RAIN",
    66: "FREEZING RAIN",
    67: "FREEZING RAIN",
    71: "LIGHT SNOW",
    73: "SNOWY",
    75: "HEAVY SNOW",
    77: "SNOW GRAINS",
    80: "RAIN SHOWERS",
    81: "RAIN SHOWERS",
    82: "HEAVY SHOWERS",
    85: "SNOW SHOWERS",
    86: "HEAVY SNOW",
    95: "THUNDERSTORM",
    96: "STORM / HAIL",
    99: "STORM / HAIL",
}

def weather_description(code):
    return WEATHER_CODES.get(code, "UNKNOWN")


def weather_graphic(code):
    if code == 0:
        return [
            r"       \  |  /",
            r"     --- ( ) ---",
            r"       /  |  \ ",
        ]

    if code in (1, 2):
        return [
            r"       \ | /",
            r"      -- O --",
            r"     .------.",
            r"    (  CLOUD  )",
        ]

    if code == 3:
        return [
            r"     .--------.",
            r"   .'          '.",
            r"  (    CLOUD     )",
            r"   '._        _.'",
        ]

    if code in (45, 48):
        return [
            "    ~ ~ ~ ~ ~ ~",
            "      F O G",
            "    ~ ~ ~ ~ ~ ~",
        ]

    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return [
            "     .--------.",
            "    (   CLOUD   )",
            "     '--------'",
            "      | | | | |",
        ]

    if code in (71, 73, 75, 77, 85, 86):
        return [
            "     .--------.",
            "    (   CLOUD   )",
            "     '--------'",
            "      * * * * *",
        ]

    if code in (95, 96, 99):
        return [
            "     .--------.",
            "    (   STORM   )",
            "     '--------'",
            "         /\\",
        ]

    return ["    WEATHER UNKNOWN"]


def get_weather():
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "apparent_temperature,"
            "weather_code,"
            "surface_pressure,"
            "wind_speed_10m,"
            "wind_direction_10m"
        ),
        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "wind_speed_10m,"
            "wind_gusts_10m,"
            "precipitation_probability,"
            "precipitation,"
            "visibility,"
            "weather_code"
        ),
        "daily": (
            "temperature_2m_max,"
            "temperature_2m_min,"
            "sunrise,"
            "sunset,"
            "precipitation_probability_max"
        ),
        "forecast_days": 1,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "pressure_unit": "hPa",
        "timezone": "Europe/London",
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def get_hourly_weather(
    weather,
    interval_hours=4,
):
    hourly = weather["hourly"]
    readings = []

    for i, timestamp in enumerate(
        hourly["time"]
    ):
        dt = datetime.fromisoformat(
            timestamp
        )

        if dt.hour % interval_hours != 0:
            continue

        readings.append({
            "time": dt.strftime("%H:%M"),
            "temperature": (
                hourly[
                    "temperature_2m"
                ][i]
            ),
            "humidity": (
                hourly[
                    "relative_humidity_2m"
                ][i]
            ),
            "wind": (
                hourly[
                    "wind_speed_10m"
                ][i]
            ),
            "gust": (hourly.get("wind_gusts_10m") or [0] * len(hourly["time"]))[i],
            "precip_probability": (hourly.get("precipitation_probability") or [0] * len(hourly["time"]))[i],
            "precipitation": (hourly.get("precipitation") or [0] * len(hourly["time"]))[i],
            "visibility": (hourly.get("visibility") or [99999] * len(hourly["time"]))[i],
            "code": (
                hourly[
                    "weather_code"
                ][i]
            ),
        })

    return readings


# ============================================================
# GOOGLE DOCS
# ============================================================

def extract_google_doc_id(value):
    value = (value or "").strip()

    if not value:
        raise ValueError("Google Docs URL/ID is empty.")

    if "docs.google.com" not in value:
        return value

    match = re.search(
        r"/document/d/([a-zA-Z0-9_-]+)",
        value,
    )

    if not match:
        raise ValueError(
            "Could not find Google Docs document ID."
        )

    return match.group(1)


def get_google_doc_text(value):
    document_id = extract_google_doc_id(value)

    export_url = (
        "https://docs.google.com/document/d/"
        f"{document_id}/export?format=txt"
    )

    response = requests.get(
        export_url,
        timeout=15,
    )
    response.raise_for_status()

    return response.text

def get_random_lines(number_of_lines):
    DOCUMENT_ID = "11SNp_UlxhLs6kHl0gzS5CDRL5gCsPzwBgkGXqJEhKUQ"
    url = f"https://docs.google.com/document/d/{DOCUMENT_ID}/export?format=txt"

    try:
        response = requests.get(url)
        response.raise_for_status()
        full_text = response.text

        # 2. Split text into lines and strip trailing whitespace/newlines
        raw_lines = full_text.splitlines()

        # 3. Clean text by removing completely empty lines
        clean_lines = [line.strip() for line in raw_lines if line.strip()]

        # 4. Check if the document has enough content
        if len(clean_lines) < number_of_lines:
            return (
                f"The document only has {len(clean_lines)} line(s). Printing all of them:"
            )

        # 5. Pick and print random unique lines
        random_lines = random.sample(clean_lines, number_of_lines)

        allfiles = "\n".join(random_lines)
        return allfiles

    except requests.exceptions.RequestException as e:
        return f"Error fetching document: {e}"

# ============================================================
# GOOGLE CALENDAR
# ============================================================

def get_calendar_events(ical_url, days_ahead=0):
    response = requests.get(ical_url, timeout=15)
    response.raise_for_status()
    calendar_data = Calendar.from_ical(response.content)
    tz = ZoneInfo("Europe/London")
    today = datetime.now(tz).date()
    start_of_day = datetime.combine(today, time.min)
    end_of_day = datetime.combine(today + timedelta(days=days_ahead), time.max)
    events = recurring_ical_events.of(calendar_data).between(start_of_day, end_of_day)
    results = []

    for event in events:
        start = event.get("DTSTART")
        end = event.get("DTEND")
        if start is None:
            continue
        sv = start.dt
        ev = end.dt if end is not None else None
        all_day = isinstance(sv, date) and not isinstance(sv, datetime)
        if all_day:
            event_date, time_string, start_dt, end_dt = sv, "ALL DAY", None, None
        else:
            if sv.tzinfo is None: sv = sv.replace(tzinfo=tz)
            else: sv = sv.astimezone(tz)
            if isinstance(ev, datetime):
                if ev.tzinfo is None: ev = ev.replace(tzinfo=tz)
                else: ev = ev.astimezone(tz)
            event_date = sv.date()
            start_dt = sv
            end_dt = ev if isinstance(ev, datetime) else sv
            time_string = sv.strftime("%H:%M")
            if isinstance(end_dt, datetime) and end_dt != sv:
                time_string += "-" + end_dt.strftime("%H:%M")

        results.append({
            "date": event_date,
            "time": time_string,
            "title": str(event.get("SUMMARY", "UNTITLED EVENT")),
            "location": str(event.get("LOCATION", "") or "").strip(),
            "start_dt": start_dt,
            "end_dt": end_dt,
            "all_day": all_day,
        })

    results.sort(key=lambda x: (x["date"], x["time"]))
    return results


# ============================================================
# PRINTER-SAFE TEXT
# ============================================================

def printer_safe_text(text):
    """
    Convert arbitrary input into conservative printable text for
    ESC/POS thermal printers while preserving the pound symbol.
    """
    if text is None:
        return ""

    text = str(text)

    replacements = {
        "\ufeff": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2022": "-",
        "\u00b7": "-",
        "\u00ae": "(R)",
        "\u00a9": "(C)",
        "\u2122": "(TM)",
        "\u20ac": "EUR",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2191": "^",
        "\u2193": "v",
        "\u00b0": " DEG ",
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    text = re.sub(
        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])",
        "",
        text,
    )

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        ch for ch in text
        if not unicodedata.combining(ch)
    )

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")

    text = "".join(
        ch
        for ch in text
        if (
            ch == "\n"
            or 32 <= ord(ch) <= 126
            or ch == "£"
        )
    )

    return text


def printer_text(printer, text):
    """Send only cleaned printable text to ESC/POS."""
    printer.text(printer_safe_text(text))

# ============================================================
# FOOD SHOP CHECK
# ============================================================

def food_shop_requested(todo_text):
    return bool(
        re.search(
            r"\bfood\s+shop\b",
            todo_text or "",
            flags=re.IGNORECASE,
        )
    )


def print_food_shop_check(
    printer,
    food_shop_text
):
    print_line(printer, "=")

    printer.set(bold=True)
    centre(printer, "FOOD SHOP")
    printer.set(bold=False)
    print_line(printer, "-")

    items = [
        printer_safe_text(line.strip())
        for line in (food_shop_text or "").splitlines()
        if line.strip()
    ]

    if not items:
        left(printer, "NO FOOD SHOP ITEMS")
        return

    for item in items:
        print_wrapped(
            printer,
            f"[ ] {item}",
            width=40,
        )

    print_line(printer, "-")


# ============================================================
# SHOPPING LIST
# ============================================================

def shopping_list_requested(todo_text):
    return bool(
        re.search(
            r"\bshopping\s+list\b",
            todo_text or "",
            flags=re.IGNORECASE,
        )
    )


def print_shopping_list(printer, shopping_list_text):
    print_line(printer, "=")

    printer.set(bold=True)
    centre(printer, "SHOPPING LIST")
    printer.set(bold=False)
    print_line(printer, "-")

    items = [
        printer_safe_text(line.strip())
        for line in (shopping_list_text or "").splitlines()
        if line.strip()
    ]

    if not items:
        left(printer, "NO SHOPPING LIST ITEMS")
        return

    for item in items:
        print_wrapped(
            printer,
            f"[ ] {item}",
            width=40,
        )

    print_line(printer, "-")

# ============================================================
# FINANCIAL STATUS - LIVE TRUE LAYER DATA
# ============================================================

def finance_check_requested(
    google_doc_text,
    now=None,
):
    """
    Finance is requested when:

    1. Today is Sunday, OR
    2. The Google Doc contains a line whose finance command
       ends with a full stop.

    Examples that trigger:
        finance.
        finance check.
        check finance.

    Examples that do not:
        finance
        finance?
        sort finance
    """
    if now is None:
        now = datetime.now(
            ZoneInfo("Europe/London")
        )

    # Sunday = 6
    if now.weekday() == 6:
        return True

    if not google_doc_text:
        return False

    for raw_line in google_doc_text.splitlines():
        line = raw_line.strip()

        # Your existing Google Doc convention:
        # actionable commands must end in a full stop.
        if not line.endswith("."):
            continue

        command = line[:-1].strip().lower()

        if command in {
            "finance",
            "finance check",
            "check finance",
        }:
            return True

    return False


def _load_truelayer_saved_tokens():
    if not TRUELAYER_TOKEN_FILE.exists():
        return {}

    try:
        data = json.loads(
            TRUELAYER_TOKEN_FILE.read_text(
                encoding="utf-8"
            )
        )
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_truelayer_tokens(tokens):
    try:
        TRUELAYER_TOKEN_FILE.write_text(
            json.dumps(tokens, indent=2),
            encoding="utf-8",
        )

        # Restrict token file permissions on macOS/Linux/Raspberry Pi.
        try:
            os.chmod(TRUELAYER_TOKEN_FILE, 0o600)
        except OSError:
            pass
    except OSError as error:
        print(
            "Could not save refreshed TrueLayer tokens:",
            error,
        )


def _initial_truelayer_refresh_token(provider):
    env_tokens = {
        "HSBC": TRUELAYER_HSBC_REFRESH_TOKEN,
        "MONZO": TRUELAYER_MONZO_REFRESH_TOKEN,
        "AMEX": TRUELAYER_AMEX_REFRESH_TOKEN,
    }

    saved = _load_truelayer_saved_tokens()

    return (
        saved.get(provider)
        or env_tokens.get(provider, "")
    )


def _refresh_truelayer_access_token(
    provider,
    refresh_token
):
    if not TRUELAYER_CLIENT_ID:
        raise RuntimeError(
            "TrueLayer client ID is not configured."
        )

    if not TRUELAYER_CLIENT_SECRET:
        raise RuntimeError(
            "TrueLayer client secret is not configured."
        )

    if not refresh_token:
        raise RuntimeError(
            f"No TrueLayer refresh token configured "
            f"for {provider}."
        )

    response = requests.post(
        TRUELAYER_AUTH_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": TRUELAYER_CLIENT_ID,
            "client_secret": TRUELAYER_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=20,
    )

    if not response.ok:
        try:
            error_data = response.json()
        except ValueError:
            error_data = response.text

        print(
            f"TrueLayer {provider} refresh failed:"
        )
        print(
            f"HTTP {response.status_code}"
        )
        print(error_data)

        raise RuntimeError(
            f"TrueLayer {provider} token refresh failed."
        )

    payload = response.json()

    access_token = payload.get(
        "access_token"
    )

    if not access_token:
        raise RuntimeError(
            f"TrueLayer returned no access token "
            f"for {provider}."
        )

    replacement_refresh = payload.get(
        "refresh_token"
    )

    if replacement_refresh:
        saved = (
            _load_truelayer_saved_tokens()
        )

        saved[provider] = (
            replacement_refresh
        )

        _save_truelayer_tokens(
            saved
        )

    return access_token

def load_manual_assets(
    filename="finance_assets.txt",
):
    assets = []

    try:
        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as file:

            for line in file:
                line = line.strip()

                if (
                    not line
                    or line.startswith("#")
                    or "|" not in line
                ):
                    continue

                name, value = line.split(
                    "|",
                    1,
                )

                try:
                    amount = float(
                        value.strip()
                    )
                except ValueError:
                    continue

                assets.append({
                    "name": name.strip(),
                    "amount": amount,
                })

    except FileNotFoundError:
        pass

    return assets

def load_regular_payments(
    filename="regular_payments.txt",
):
    """
    Format:

    DISPLAY NAME | AMOUNT | DAY | MATCH TERMS

    Example:

    Council Tax | 142.00 | 5 |
    birmingham city council,birmingham cc
    """

    payments = []

    try:
        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as file:

            for line in file:
                line = line.strip()

                if (
                    not line
                    or line.startswith("#")
                ):
                    continue

                parts = [
                    part.strip()
                    for part in line.split("|")
                ]

                if len(parts) < 3:
                    continue

                try:
                    amount = float(
                        parts[1]
                    )

                    day = int(
                        parts[2]
                    )

                except ValueError:
                    continue

                if not 1 <= day <= 31:
                    continue

                match_terms = []

                if len(parts) >= 4:
                    match_terms = [
                        term.strip().lower()
                        for term
                        in parts[3].split(",")
                        if term.strip()
                    ]

                # Use the friendly name as a
                # fallback matching term.
                if not match_terms:
                    match_terms = [
                        parts[0].lower()
                    ]

                payments.append({
                    "name": parts[0],
                    "amount": amount,
                    "day": day,
                    "match_terms": match_terms,
                    "type": payment_type,
                })

                payment_type = "other"

                if len(parts) >= 5:
                    payment_type = (
                        parts[4]
                        .strip()
                        .lower()
                    )

    except FileNotFoundError:
        pass

    return payments

def transaction_amount(transaction):
    try:
        return float(
            transaction.get(
                "amount",
                0.0,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0.0


def transaction_description(
    transaction,
):
    return str(
        transaction.get(
            "description",
            transaction.get(
                "merchant_name",
                transaction.get(
                    "transaction_type",
                    "",
                ),
            ),
        )
    ).strip()


def transaction_date(transaction):
    value = (
        transaction.get("timestamp")
        or transaction.get(
            "transaction_date"
        )
        or transaction.get(
            "date"
        )
    )

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        ).date()

    except ValueError:
        try:
            return datetime.strptime(
                str(value)[:10],
                "%Y-%m-%d",
            ).date()

        except ValueError:
            return None

SPENDING_RULES = {
    "food": (
        "tesco",
        "sainsbury",
        "aldi",
        "lidl",
        "morrisons",
        "waitrose",
        "ocado",
        "coop",
        "co-op",
    ),

    "taxis": (
        "uber",
        "bolt",
        "free now",
    ),

    "transport": (
        "trainline",
        "national rail",
        "west midlands",
        "tfl",
    ),

    "eating_out": (
        "restaurant",
        "deliveroo",
        "just eat",
        "ubereats",
    ),
}


def categorise_transaction(
    transaction,
):
    description = (
        transaction_description(
            transaction
        ).lower()
    )

    for category, terms in (
        SPENDING_RULES.items()
    ):
        if any(
            term in description
            for term in terms
        ):
            return category

    return "other"

def payment_made_this_month(
    payment,
    transactions,
):
    """
    Check transaction history to determine
    whether a known regular payment has already
    been made this month.
    """

    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    match_terms = payment.get(
        "match_terms",
        [],
    )

    expected_amount = payment[
        "amount"
    ]

    for transaction in (
        transactions or []
    ):
        tx_date = transaction_date(
            transaction
        )

        if not tx_date:
            continue

        if (
            tx_date.year != today.year
            or tx_date.month != today.month
        ):
            continue

        amount = transaction_amount(
            transaction
        )

        # We're looking for money leaving.
        if amount >= 0:
            continue

        description = (
            transaction_description(
                transaction
            ).lower()
        )

        name_matches = any(
            term in description
            for term in match_terms
        )

        # Allow a little movement for bills
        # such as energy.
        tolerance = max(
            2.00,
            expected_amount * 0.10,
        )

        amount_matches = (
            abs(
                abs(amount)
                - expected_amount
            )
            <= tolerance
        )

        if (
            name_matches
            and amount_matches
        ):
            return True

    return False

def calculate_runway(
    available_money,
    monthly_burn,
):
    if monthly_burn <= 0:
        return {
            "months": 0.0,
            "days": 0,
        }

    months = (
        available_money
        / monthly_burn
    )

    days = int(
        months * 30.44
    )

    return {
        "months": months,
        "days": days,
    }

def analyse_regular_payments(
    payments,
    transactions,
):
    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    made = []
    remaining = []

    for payment in payments:
        paid = (
            payment_made_this_month(
                payment,
                transactions,
            )
        )

        result = dict(payment)

        result["paid"] = paid

        if paid:
            made.append(result)

        else:
            remaining.append(result)

    remaining_total = sum(
        payment["amount"]
        for payment in remaining
    )

    return {
        "made": made,
        "remaining": remaining,
        "remaining_total": (
            remaining_total
        ),
    }

def calculate_rest_of_month(
    cash_available,
    remaining_bills,
):
    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    days_in_month = (
        calendar.monthrange(
            today.year,
            today.month,
        )[1]
    )

    days_remaining = max(
        days_in_month
        - today.day
        + 1,
        1,
    )

    after_bills = (
        cash_available
        - remaining_bills
    )

    daily_allowance = (
        max(
            after_bills,
            0.0,
        )
        / days_remaining
    )

    return {
        "days_remaining": (
            days_remaining
        ),
        "after_bills": (
            after_bills
        ),
        "daily_allowance": (
            daily_allowance
        ),
    }

ESSENTIAL_CATEGORIES = {
    "food",
    "transport",
    "housing",
    "utilities",
}

def historical_essential_spending(
    transactions,
    regular_payments,
    months=3,
):
    """
    Estimate essential monthly expenditure from
    historical transaction data.
    """

    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    target_year = today.year
    target_month = today.month

    totals = []

    for _ in range(months):
        target_year, target_month = (
            previous_month(
                target_year,
                target_month,
            )
        )

        total = 0.0

        for transaction in (
            transactions or []
        ):
            tx_date = transaction_date(
                transaction
            )

            if not tx_date:
                continue

            if (
                tx_date.year != target_year
                or
                tx_date.month
                != target_month
            ):
                continue

            amount = transaction_amount(
                transaction
            )

            if amount >= 0:
                continue

            category = (
                categorise_transaction(
                    transaction
                )
            )

            if category in (
                ESSENTIAL_CATEGORIES
            ):
                total += abs(amount)

        # Known fixed commitments should also
        # be regarded as essential.
        known_commitments = sum(
            payment["amount"]
            for payment
            in regular_payments
            if payment["name"].lower()
            not in (
                "spotify",
                "netflix",
            )
        )

        total = max(
            total,
            known_commitments,
        )

        if total > 0:
            totals.append(total)

    if not totals:
        return 0.0

    return (
        sum(totals)
        / len(totals)
    )



def build_finance_snapshot(
    hsbc_available,
    monzo_available,
    amex_owed,
    transactions,
    direct_debits=None,
    standing_orders=None,
):
    manual_assets = (
        load_manual_assets()
    )

    cash_available = (
        hsbc_available
        + monzo_available
    )

    manual_asset_total = sum(
        item["amount"]
        for item in manual_assets
    )

    net_position = (
        cash_available
        + manual_asset_total
        - amex_owed
    )

    cashflow = (
        calculate_month_cashflow(
            transactions
        )
    )

    regular_payments = (
        load_regular_payments()
    )

    payment_analysis = (
        analyse_regular_payments(
            regular_payments,
            transactions,
        )
    )

    rest_of_month = (
        calculate_rest_of_month(
            cash_available,
            payment_analysis[
                "remaining_total"
            ],
        )
    )

    observations = (
        generate_finance_observations(
            transactions,
            cashflow,
        )
    )

    # Initially use current monthly
    # outgoings as the burn estimate.
    monthly_burn = max(
        cashflow["outgoings"],
        0.0,
    )

    historical_spending = (
        historical_monthly_spending(
            transactions,
            months=6,
        )
    )

    monthly_burn = (
        historical_spending[
            "average"
        ]
    )
    runway = calculate_runway(
        cash_available,
        monthly_burn,
    )
    return {
        "hsbc": hsbc_available,
        "monzo": monzo_available,
        "amex": amex_owed,

        "manual_assets": (
            manual_assets
        ),

        "cash_available": (
            cash_available
        ),

        "net_position": (
            net_position
        ),

        "cashflow": cashflow,

        "direct_debits": (
            direct_debits or []
        ),

        "standing_orders": (
            standing_orders or []
        ),

        "payments": (
            payment_analysis
        ),

        "rest_of_month": (
            rest_of_month
        ),

        "observations": (
            observations
        ),

        "monthly_burn": (
            monthly_burn
        ),

        "runway": runway,
    }

def payment_made_this_month(
    payment,
    transactions,
):
    """
    Check transaction history to determine
    whether a known regular payment has already
    been made this month.
    """

    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    match_terms = payment.get(
        "match_terms",
        [],
    )

    expected_amount = payment[
        "amount"
    ]

    for transaction in (
        transactions or []
    ):
        tx_date = transaction_date(
            transaction
        )

        if not tx_date:
            continue

        if (
            tx_date.year != today.year
            or tx_date.month != today.month
        ):
            continue

        amount = transaction_amount(
            transaction
        )

        # We're looking for money leaving.
        if amount >= 0:
            continue

        description = (
            transaction_description(
                transaction
            ).lower()
        )

        name_matches = any(
            term in description
            for term in match_terms
        )

        # Allow a little movement for bills
        # such as energy.
        tolerance = max(
            2.00,
            expected_amount * 0.10,
        )

        amount_matches = (
            abs(
                abs(amount)
                - expected_amount
            )
            <= tolerance
        )

        if (
            name_matches
            and amount_matches
        ):
            return True

    return False

def previous_month(
    year,
    month,
):
    month -= 1

    if month == 0:
        month = 12
        year -= 1

    return year, month

def historical_category_average(
    transactions,
    category,
    months=3,
):
    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    totals = []

    year = today.year
    month = today.month

    for offset in range(
        1,
        months + 1,
    ):
        target_month = month - offset
        target_year = year

        while target_month <= 0:
            target_month += 12
            target_year -= 1

        total = 0.0

        for transaction in (
            transactions or []
        ):
            tx_date = transaction_date(
                transaction
            )

            if not tx_date:
                continue

            if (
                tx_date.year
                != target_year
                or tx_date.month
                != target_month
            ):
                continue

            # Compare equivalent portions
            # of each month.
            if tx_date.day > today.day:
                continue

            amount = transaction_amount(
                transaction
            )

            if amount >= 0:
                continue

            if (
                categorise_transaction(
                    transaction
                )
                != category
            ):
                continue

            total += abs(amount)

        totals.append(total)

    useful = [
        value
        for value in totals
        if value > 0
    ]

    if not useful:
        return 0.0

    return (
        sum(useful)
        / len(useful)
    )

def generate_finance_observations(
    transactions,
    cashflow,
):
    observations = []

    categories = cashflow[
        "categories"
    ]

    for category in (
        "food",
        "taxis",
        "eating_out",
        "transport",
    ):
        current = categories.get(
            category,
            0.0,
        )

        normal = (
            historical_category_average(
                transactions,
                category,
            )
        )

        if normal <= 0:
            continue

        difference = (
            (current - normal)
            / normal
            * 100
        )

        if difference >= 20:
            observations.append(
                (
                    f"{category.replace('_', ' ').title()} "
                    f"spending is {difference:.0f}% "
                    "above normal."
                )
            )

    if cashflow["net"] < 0:
        observations.append(
            "Outgoings currently exceed "
            "income this month."
        )

    return observations

def historical_monthly_spending(
    transactions,
    months=3,
):


    """
    Calculate spending during previous completed
    calendar months.

    The current partial month is deliberately
    excluded.
    """

    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    target_year = today.year
    target_month = today.month

    monthly_totals = []

    for _ in range(months):
        target_year, target_month = (
            previous_month(
                target_year,
                target_month,
            )
        )

        total = 0.0

        for transaction in (
            transactions or []
        ):
            tx_date = transaction_date(
                transaction
            )

            if not tx_date:
                continue

            if (
                tx_date.year != target_year
                or
                tx_date.month
                != target_month
            ):
                continue

            amount = transaction_amount(
                transaction
            )

            if amount < 0:
                total += abs(amount)

        if total > 0:
            monthly_totals.append({
                "year": target_year,
                "month": target_month,
                "amount": total,
            })

    if not monthly_totals:
        return {
            "average": 0.0,
            "months": [],
        }

    average = (
        sum(
            item["amount"]
            for item in monthly_totals
        )
        / len(monthly_totals)
    )

    return {
        "average": average,
        "months": monthly_totals,
    }

def _truelayer_get(access_token, endpoint):
    response = requests.get(
        f"{TRUELAYER_DATA_URL}{endpoint}",
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _get_first_account_balance(access_token):
    """
    Return live balance data for the first bank account exposed by
    this TrueLayer connection.
    """
    account_data = _truelayer_get(
        access_token,
        "/accounts",
    )

    accounts = account_data.get("results", [])

    if not accounts:
        raise RuntimeError(
            "No bank account was returned by TrueLayer."
        )

    account_id = accounts[0].get("account_id")

    if not account_id:
        raise RuntimeError(
            "TrueLayer account has no account_id."
        )

    balance_data = _truelayer_get(
        access_token,
        f"/accounts/{account_id}/balance",
    )

    balances = balance_data.get("results", [])

    if not balances:
        raise RuntimeError(
            "TrueLayer returned no account balance."
        )

    return balances[0]


def _get_first_card_balance(access_token):
    """
    Return live balance data for the first credit card exposed by
    this TrueLayer connection.
    """
    card_data = _truelayer_get(
        access_token,
        "/cards",
    )

    cards = card_data.get("results", [])

    if not cards:
        raise RuntimeError(
            "No credit card was returned by TrueLayer."
        )

    account_id = cards[0].get("account_id")

    if not account_id:
        raise RuntimeError(
            "TrueLayer card has no account_id."
        )

    balance_data = _truelayer_get(
        access_token,
        f"/cards/{account_id}/balance",
    )

    balances = balance_data.get("results", [])

    if not balances:
        raise RuntimeError(
            "TrueLayer returned no card balance."
        )

    return balances[0]


def get_account_balances():
    """
    Retrieve real HSBC, Monzo and American Express balances from
    TrueLayer.

    HSBC/Monzo use account balance endpoints.
    American Express uses the credit-card balance endpoint.
    """
    hsbc_token = _refresh_truelayer_access_token(
        "HSBC",
        _initial_truelayer_refresh_token("HSBC"),
    )
    monzo_token = _refresh_truelayer_access_token(
        "MONZO",
        _initial_truelayer_refresh_token("MONZO"),
    )
    amex_token = _refresh_truelayer_access_token(
        "AMEX",
        _initial_truelayer_refresh_token("AMEX"),
    )
    hsbc = _get_first_account_balance(hsbc_token)
    monzo = _get_first_account_balance(monzo_token)
    amex = _get_first_card_balance(amex_token)

    return {
        "HSBC": {
            "current": float(hsbc.get("current", 0.0)),
            "available": float(
                hsbc.get(
                    "available",
                    hsbc.get("current", 0.0),
                )
            ),
            "currency": hsbc.get("currency", "GBP"),
        },
        "MONZO": {
            "current": float(monzo.get("current", 0.0)),
            "available": float(
                monzo.get(
                    "available",
                    monzo.get("current", 0.0),
                )
            ),
            "currency": monzo.get("currency", "GBP"),
        },
        "AMEX": {
            # For TrueLayer card balances, current is expenditure /
            # amount currently owed on the card.
            "current": float(amex.get("current", 0.0)),
            "available": float(amex.get("available", 0.0)),
            "credit_limit": float(
                amex.get("credit_limit", 0.0)
            ),
            "currency": amex.get("currency", "GBP"),
        },
    }

def finance_quick_summary(
    snapshot,
):
    """
    Build a short summary for the bottom of the
    finance receipt.
    """

    lines = []

    cashflow = snapshot.get(
        "cashflow",
        {},
    )

    rest = snapshot.get(
        "rest_of_month",
        {},
    )

    normal_runway = snapshot.get(
        "normal_runway",
        {},
    )

    essential_runway = snapshot.get(
        "essential_runway",
        {},
    )

    observations = snapshot.get(
        "observations",
        [],
    )

    # ------------------------------------
    # CASH FLOW
    # ------------------------------------

    net_cashflow = float(
        cashflow.get(
            "net",
            0.0,
        )
        or 0.0
    )

    if net_cashflow > 0:
        lines.append(
            (
                f"Cash flow is positive by {format_money(net_cashflow)} this month."
            )
        )

    elif net_cashflow < 0:
        lines.append(
            (
                f"Cash flow is negative by {format_money(net_cashflow)} this month."
            )
        )

    else:
        lines.append(
            "Cash flow is currently even "
            "this month."
        )

    # ------------------------------------
    # MONEY AFTER BILLS
    # ------------------------------------

    after_bills = float(
        rest.get(
            "after_bills",
            0.0,
        )
        or 0.0
    )

    if after_bills >= 0:
        lines.append(
            (
                f"{format_money(after_bills)} remains after known bills."
            )
        )

    else:
        lines.append(
            (
                f"Known remaining bills exceed available cash by {format_money(after_bills)}"
            )
        )

    # ------------------------------------
    # DAILY ALLOWANCE
    # ------------------------------------

    daily_allowance = float(
        rest.get(
            "daily_allowance",
            0.0,
        )
        or 0.0
    )

    days_remaining = int(
        rest.get(
            "days_remaining",
            0,
        )
        or 0
    )

    if (
        daily_allowance > 0
        and days_remaining > 0
    ):
        lines.append(
            (
                f"About £ {daily_allowance:.2f} "
                "per day is available for the "
                f"remaining {days_remaining} days."
            )
        )

    # ------------------------------------
    # SPENDING OBSERVATIONS
    # ------------------------------------

    for observation in observations[:2]:
        lines.append(
            str(observation)
        )

    # ------------------------------------
    # RUNWAY
    # ------------------------------------

    normal_days = int(
        normal_runway.get(
            "days",
            0,
        )
        or 0
    )

    essential_days = int(
        essential_runway.get(
            "days",
            0,
        )
        or 0
    )

    if normal_days > 0:
        lines.append(
            (
                "Current lifestyle runway is "
                f"about {normal_days} days."
            )
        )

    if (
        essential_days > 0
        and essential_days != normal_days
    ):
        lines.append(
            (
                "Essential-only runway is "
                f"about {essential_days} days."
            )
        )

    return lines

def load_subscriptions():
    if not SUBSCRIPTIONS_FILE.exists():
        return {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        }

    try:
        with SUBSCRIPTIONS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(
            "Subscription file error:",
            repr(error),
        )

        return {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        }

    if not isinstance(data, dict):
        return {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        }

    data.setdefault("monthly", [])
    data.setdefault("yearly", [])
    data.setdefault("instalments", [])

    return data


def subscription_was_paid(
    subscription,
    transactions,
    today,
):
    """
    Return True when a transaction matching this
    subscription exists in the current month.

    Matches using:
      - merchant description
      - expected amount, when configured
    """

    match_terms = (
        subscription.get(
            "match",
            []
        )
    )

    if isinstance(
            match_terms,
            str,
    ):
        match_terms = [
            match_terms
        ]

    match_terms = [
        str(term).strip().lower()
        for term in match_terms
        if str(term).strip()
    ]

    expected_amount = (
        subscription.get("amount")
    )

    try:
        if expected_amount is not None:
            expected_amount = float(
                expected_amount
            )

    except (
        TypeError,
        ValueError,
    ):
        expected_amount = None

    for transaction in transactions:

        # --------------------------------------
        # DATE
        # --------------------------------------

        timestamp = transaction.get(
            "timestamp"
        )

        if not timestamp:
            continue

        try:
            transaction_date = (
                datetime.fromisoformat(
                    str(timestamp).replace(
                        "Z",
                        "+00:00",
                    )
                ).date()
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        # Only inspect the current month.
        if (
            transaction_date.year
            != today.year
            or transaction_date.month
            != today.month
        ):
            continue

        # --------------------------------------
        # DESCRIPTION
        # --------------------------------------

        transaction_name = str(
            transaction.get("merchant_name")
            or transaction.get("description")
            or ""
        ).strip().lower()

        if not any(
                term in transaction_name
                for term in match_terms
        ):
            continue

        # --------------------------------------
        # AMOUNT
        # --------------------------------------

        if expected_amount is not None:

            try:
                transaction_amount = abs(
                    float(
                        transaction.get(
                            "amount",
                            0,
                        )
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            # Allow tiny rounding differences.
            if (
                abs(
                    transaction_amount
                    - expected_amount
                )
                > 0.01
            ):
                continue

        # Merchant and amount matched.
        return True

    return False

def build_subscription_status(
    transactions,
):
    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    subscriptions = (
        load_subscriptions()
    )

    monthly = []

    for subscription in (
        subscriptions.get(
            "monthly",
            []
        )
    ):
        item = dict(
            subscription
        )

        item["paid"] = (
            subscription_was_paid(
                subscription,
                transactions,
                today,
            )
        )

        monthly.append(
            item
        )

    return {
        "monthly": monthly,
        "yearly": subscriptions.get(
            "yearly",
            [],
        ),
    }

def print_subscription_changes(
    printer,
    changes,
):
    if not changes:
        return

    print_line(
        printer,
        "-",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        "BILL CHANGES",
    )

    printer.set(
        bold=False
    )

    for change in changes:

        name = printer_safe_text(
            change.get(
                "name",
                "SUBSCRIPTION",
            )
        ).upper()

        old_amount = float(
            change.get(
                "old_amount",
                0,
            )
        )

        new_amount = float(
            change.get(
                "new_amount",
                0,
            )
        )

        difference = float(
            change.get(
                "difference",
                0,
            )
        )

        percentage = float(
            change.get(
                "percentage",
                0,
            )
        )

        left(
            printer,
            name[:40],
        )

        left(
            printer,
            (
                f"  £{old_amount:.2f}"
                f" -> "
                f"£{new_amount:.2f}"
            ),
        )

        left(
            printer,
            (
                f"  {difference:+.2f} GBP"
                f"  "
                f"{percentage:+.1f}%"
            ),
        )

def print_instalment_status(printer, subscriptions_data):
    instalments = subscriptions_data.get(
        "instalments",
        []
    )

    if not instalments:
        return

    printer.set(bold=True)
    left(printer, "INSTALMENTS")
    printer.set(bold=False)

    monthly_total = 0.0
    known_balance = 0.0

    for item in instalments:
        name = printer_safe_text(
            str(item.get("name", "INSTALMENT"))
        )

        amount = _safe_amount(
            item.get("amount")
        )

        monthly_total += amount

        balance = item.get("remaining_balance")
        payments_left = item.get("payments_remaining")

        left(
            printer,
            f"{name[:24]}"
        )

        if payments_left is not None:
            left(
                printer,
                (
                    f" £{amount:.2f}/mo"
                    f"   {payments_left} payments left"
                )
            )
        else:
            left(
                printer,
                f" £{amount:.2f}/mo"
            )

        if balance is not None:
            balance = _safe_amount(balance)
            known_balance += balance

            left(
                printer,
                f" £{balance:.2f} remaining"
            )

    print_line(printer, "-")

    left(
        printer,
        f"INSTALMENTS / MONTH   £{monthly_total:.2f}"
    )

    if known_balance > 0:
        left(
            printer,
            f"KNOWN BALANCE         £{known_balance:.2f}"
        )



def print_subscription_status(
    printer,
    left,
    print_line,
    transactions,
):
    status = build_subscription_status(
        transactions
    )

    monthly = status.get(
        "monthly",
        [],
    )

    if not monthly:
        return

    paid = []
    due = []

    for item in monthly:
        try:
            amount = float(
                item.get("amount", 0)
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            amount = 0.0

        row = {
            "name": str(
                item.get(
                    "name",
                    "Subscription",
                )
            ),
            "amount": amount,
            "category": item.get(
                "category",
                "",
            ),
        }

        if item.get("paid"):
            paid.append(row)
        else:
            due.append(row)

    paid_total = sum(
        item["amount"]
        for item in paid
    )

    due_bills = sum(
        item["amount"]
        for item in due
        if item["category"] != "savings"
    )

    due_savings = sum(
        item["amount"]
        for item in due
        if item["category"] == "savings"
    )

    remaining_total = (
        due_bills
        + due_savings
    )

    # ==========================================
    # HEADER
    # ==========================================

    print_line(
        printer,
        "=",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        "MONTHLY COMMITMENTS",
    )

    printer.set(
        bold=False
    )

    print_line(
        printer,
        "-",
    )

    # ==========================================
    # PAID
    # ==========================================

    printer.set(
        bold=True
    )

    left(
        printer,
        "PAID",
    )

    printer.set(
        bold=False
    )

    if paid:
        for item in paid:

            name = item["name"]

            # Shorter receipt-friendly names.
            display_names = {
                "HLAM Regular Saving":
                    "HLAM",
                "Severn Trent Water":
                    "Water",
                "Birmingham City Council":
                    "Council Tax",
            }

            name = display_names.get(
                name,
                name,
            )

            left(
                printer,
                (
                    f"{name[:22]:<22}"
                    f"£{item['amount']:>8.2f}"
                ),
            )

    else:
        left(
            printer,
            "None",
        )

    print_line(
        printer,
        "-",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        (
            f"{'PAID TOTAL':<22}"
            f"£{paid_total:>8.2f}"
        ),
    )

    printer.set(
        bold=False
    )

    # ==========================================
    # DUE
    # ==========================================

    left(
        printer,
        "",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        "DUE",
    )

    printer.set(
        bold=False
    )

    if due:
        for item in due:

            name = item["name"]

            display_names = {
                "HLAM Regular Saving":
                    "HLAM",
                "Severn Trent Water":
                    "Water",
                "Birmingham City Council":
                    "Council Tax",
            }

            name = display_names.get(
                name,
                name,
            )

            left(
                printer,
                (
                    f"{name[:22]:<22}"
                    f"£{item['amount']:>8.2f}"
                ),
            )

    else:
        left(
            printer,
            "None",
        )

    print_line(
        printer,
        "-",
    )

    # Only show the bills/savings split when
    # something is actually outstanding.
    if due:

        if due_bills:
            left(
                printer,
                (
                    f"{'BILLS DUE':<22}"
                    f"£{due_bills:>8.2f}"
                ),
            )

        if due_savings:
            left(
                printer,
                (
                    f"{'SAVINGS DUE':<22}"
                    f"£{due_savings:>8.2f}"
                ),
            )

    printer.set(
        bold=True
    )

    left(
        printer,
        (
            f"{'REMAINING':<22}"
            f"£{remaining_total:>8.2f}"
        ),
    )

    printer.set(
        bold=False
    )

    print_line(
        printer,
        "=",
    )

def print_financial_status(
    printer,
    balances,
    snapshot=None,
):
    """
    Print the complete finance report.

    balances:
        Existing TrueLayer balance dictionary.

    snapshot:
        Result from build_finance_snapshot().
    """

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "FINANCIAL STATUS",
    )
    printer.set(bold=False)

    print_line(printer, "=")

    # ====================================
    # ACCOUNT BALANCES
    # ====================================

    hsbc = balances.get(
        "HSBC",
        {},
    )

    monzo = balances.get(
        "MONZO",
        {},
    )

    amex = balances.get(
        "AMEX",
        {},
    )

    hsbc_available = float(
        hsbc.get(
            "available",
            0.0,
        )
        or 0.0
    )

    monzo_available = float(
        monzo.get(
            "available",
            0.0,
        )
        or 0.0
    )

    amex_owed = float(
        amex.get(
            "current",
            0.0,
        )
        or 0.0
    )

    left(
        printer,
        (
            f"HSBC AVAILABLE {format_money(hsbc_available)}"
        ),
    )

    left(
        printer,
        (
            f"MONZO AVAILABLE {format_money(monzo_available)}"
        ),
    )

    left(
        printer,
        (
            f"AMEX OWED {format_money(monzo_available)}"
        ),
    )

    print_line(printer, "-")

    cash_available = (
        hsbc_available
        + monzo_available
    )

    net_after_amex = (
        cash_available
        - amex_owed
    )

    left(
        printer,
        (
            f"CASH AVAILABLE {format_money(cash_available)}"
        ),
    )

    left(
        printer,
        (
            f"AFTER AMEX     {format_money(net_after_amex)}"
        ),
    )

    if snapshot is None:
        print_line(printer, "=")
        return

    # ====================================
    # OTHER ASSETS
    # ====================================

    manual_assets = snapshot.get(
        "manual_assets",
        [],
    )

    if manual_assets:

        print_line(printer, "-")

        printer.set(bold=True)
        left(
            printer,
            "OTHER ASSETS",
        )
        printer.set(bold=False)

        for asset in manual_assets:

            name = str(
                asset.get(
                    "name",
                    "ASSET",
                )
            )

            amount = float(
                asset.get(
                    "amount",
                    0.0,
                )
                or 0.0
            )

            left(
                printer,
                (
                    f"{name[:20]:<20} {format_money(amount)}"
                ),
            )

        print_line(printer, "-")

        net_position = float(
            snapshot.get(
                "net_position",
                net_after_amex,
            )
            or 0.0
        )

        left(
            printer,
            (
                f"NET POSITION   {format_money(net_position)}"

            ),
        )

    # ====================================
    # CASH FLOW
    # ====================================

    cashflow = snapshot.get(
        "cashflow",
        {},
    )

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "CASH FLOW - THIS MONTH",
    )
    printer.set(bold=False)

    income = float(
        cashflow.get(
            "income",
            0.0,
        )
        or 0.0
    )

    outgoings = float(
        cashflow.get(
            "outgoings",
            0.0,
        )
        or 0.0
    )

    net_cashflow = float(
        cashflow.get(
            "net",
            income - outgoings,
        )
        or 0.0
    )

    left(
        printer,
        f"INCOMING        GBP {income:>9.2f}",
    )

    left(
        printer,
        f"OUTGOING        GBP {outgoings:>9.2f}",
    )

    print_line(printer, "-")

    left(
        printer,
        f"NET             GBP {net_cashflow:>9.2f}",
    )

    # ====================================
    # SPENDING CATEGORIES
    # ====================================

    categories = cashflow.get(
        "categories",
        {},
    )

    if categories:

        print_line(printer, "-")

        printer.set(bold=True)
        left(
            printer,
            "SPENDING",
        )
        printer.set(bold=False)

        category_order = (
            "food",
            "eating_out",
            "taxis",
            "transport",
            "shopping",
            "other",
        )

        printed_categories = set()

        for category in category_order:

            amount = float(
                categories.get(
                    category,
                    0.0,
                )
                or 0.0
            )

            if amount <= 0:
                continue

            printed_categories.add(
                category
            )

            name = (
                category
                .replace("_", " ")
                .upper()
            )

            left(
                printer,
                (
                    f"{name[:20]:<20} {format_money(amount)}"

                ),
            )

        # Print any categories that have
        # been added later.
        for category, value in (
            categories.items()
        ):

            if category in printed_categories:
                continue

            amount = float(
                value or 0.0
            )

            if amount <= 0:
                continue

            name = (
                str(category)
                .replace("_", " ")
                .upper()
            )

            left(
                printer,
                (
                    f"{name[:20]:<20} {format_money(amount)}"
                ),
            )

    # ====================================
    # REGULAR PAYMENTS
    # ====================================

    payments = snapshot.get(
        "payments",
        {},
    )

    payments_made = payments.get(
        "made",
        [],
    )

    payments_remaining = payments.get(
        "remaining",
        [],
    )

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "PAYMENTS MADE",
    )
    printer.set(bold=False)

    if not payments_made:
        left(
            printer,
            "NONE IDENTIFIED",
        )

    else:
        for payment in payments_made:

            name = str(
                payment.get(
                    "name",
                    "PAYMENT",
                )
            )

            amount = float(
                payment.get(
                    "amount",
                    0.0,
                )
                or 0.0
            )

            left(
                printer,
                (
                    f"[X] {name[:17]:<17} {format_money(amount)}"
                ),
            )

    # ====================================
    # PAYMENTS STILL DUE
    # ====================================

    print_line(printer, "-")

    printer.set(bold=True)
    left(
        printer,
        "STILL TO PAY",
    )
    printer.set(bold=False)

    if not payments_remaining:

        left(
            printer,
            "NO KNOWN PAYMENTS",
        )

    else:
        for payment in (
            payments_remaining
        ):

            name = str(
                payment.get(
                    "name",
                    "PAYMENT",
                )
            )

            amount = float(
                payment.get(
                    "amount",
                    0.0,
                )
                or 0.0
            )

            day = payment.get(
                "day"
            )

            if day:
                label = (
                    f"[ ] {name[:14]} "
                    f"{int(day):02d}"
                )
            else:
                label = (
                    f"[ ] {name[:17]}"
                )

            left(
                printer,
                (
                    f"{label:<21} {format_money(amount)}"
                ),
            )

        print_line(printer, "-")

        remaining_total = float(
            payments.get(
                "remaining_total",
                0.0,
            )
            or 0.0
        )

        left(
            printer,
            (
                f"TOTAL STILL DUE {format_money(remaining_total)}"
            ),
        )

    # ====================================
    # DIRECT DEBITS
    # ====================================

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "DIRECT DEBITS",
    )
    printer.set(bold=False)

    direct_debits = snapshot.get(
        "direct_debits",
        [],
    )

    if not direct_debits:

        left(
            printer,
            "NONE RETURNED BY BANK",
        )

    else:
        for payment in direct_debits:

            name = (
                payment.get("name")
                or payment.get(
                    "reference"
                )
                or payment.get(
                    "description"
                )
                or "DIRECT DEBIT"
            )

            print_wrapped(
                printer,
                printer_safe_text(
                    str(name)
                ),
                width=40,
            )

    # ====================================
    # STANDING ORDERS
    # ====================================

    print_line(printer, "-")

    printer.set(bold=True)
    left(
        printer,
        "STANDING ORDERS",
    )
    printer.set(bold=False)

    standing_orders = snapshot.get(
        "standing_orders",
        [],
    )

    if not standing_orders:

        left(
            printer,
            "NONE RETURNED BY BANK",
        )

    else:
        for payment in standing_orders:

            name = (
                payment.get("name")
                or payment.get(
                    "reference"
                )
                or payment.get(
                    "description"
                )
                or "STANDING ORDER"
            )

            print_wrapped(
                printer,
                printer_safe_text(
                    str(name)
                ),
                width=40,
            )

    # ====================================
    # SUBSCRIPTIONS
    # ====================================
    regular_payments = (
        load_regular_payments()
    )

    subscriptions = [
        payment
        for payment in regular_payments
        if payment.get(
            "type"
        ) == "subscription"
    ]

    if subscriptions:

        print_line(printer, "=")

        printer.set(bold=True)
        left(
            printer,
            "SUBSCRIPTIONS",
        )
        printer.set(bold=False)

        subscription_total = 0.0

        for subscription in subscriptions:

            amount = float(
                subscription.get(
                    "amount",
                    0.0,
                )
                or 0.0
            )

            subscription_total += amount

            name = str(
                subscription.get(
                    "name",
                    "SUBSCRIPTION",
                )
            )

            left(
                printer,
                (
                    f"{name[:20]:<20} {format_money(amount)}"
                ),
            )

        print_line(printer, "-")

        left(
            printer,
            (
                f"MONTHLY TOTAL    {format_money(subscription_total)}"
            ),
        )

    # ====================================
    # OBSERVATIONS
    # ====================================

    observations = snapshot.get(
        "observations",
        [],
    )

    if observations:

        print_line(printer, "=")

        printer.set(bold=True)
        left(
            printer,
            "OBSERVATIONS",
        )
        printer.set(bold=False)

        for observation in observations:

            print_wrapped(
                printer,
                (
                    "! "
                    + printer_safe_text(
                        str(observation)
                    )
                ),
                width=40,
            )

    # ====================================
    # REST OF MONTH
    # ====================================

    rest = snapshot.get(
        "rest_of_month",
        {},
    )

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "REST OF MONTH",
    )
    printer.set(bold=False)

    remaining_bills = float(
        payments.get(
            "remaining_total",
            0.0,
        )
        or 0.0
    )

    after_bills = float(
        rest.get(
            "after_bills",
            cash_available
            - remaining_bills,
        )
        or 0.0
    )

    days_remaining = int(
        rest.get(
            "days_remaining",
            0,
        )
        or 0
    )

    daily_allowance = float(
        rest.get(
            "daily_allowance",
            0.0,
        )
        or 0.0
    )

    left(
        printer,
        (
            f"CASH AVAILABLE   {format_money(cash_available)}"
        ),
    )

    left(
        printer,
        (
            f"BILLS STILL DUE  {format_money(remaining_bills)}"
        ),
    )

    print_line(printer, "-")

    left(
        printer,
        (
            f"FREE AFTER BILLS {format_money(after_bills)}"
        ),
    )

    left(
        printer,
        (
            "DAYS REMAINING   "
            f"{days_remaining:>13}"
        ),
    )

    left(
        printer,
        (
            f"DAILY ALLOWANCE  {format_money(daily_allowance)}"
        ),
    )

    # ====================================
    # RUNWAY
    # ====================================

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "RUNWAY",
    )
    printer.set(bold=False)

    monthly_burn = float(
        snapshot.get(
            "monthly_burn",
            0.0,
        )
        or 0.0
    )

    essential_burn = float(
        snapshot.get(
            "essential_burn",
            0.0,
        )
        or 0.0
    )

    left(
        printer,
        (
            f"6M AVG SPEND     {format_money(monthly_burn)}"
        ),
    )

    left(
        printer,
        (
            f"ESSENTIAL BURN   {format_money(essential_burn)}"
        ),
    )

    normal_runway = snapshot.get(
        "normal_runway",
        {},
    )

    essential_runway = snapshot.get(
        "essential_runway",
        {},
    )

    print_line(printer, "-")

    left(
        printer,
        "CURRENT LIFESTYLE",
    )

    left(
        printer,
        (
            f"{normal_runway.get('months', 0):.2f} "
            "MONTHS / "
            f"{normal_runway.get('days', 0)} DAYS"
        ),
    )

    left(
        printer,
        "ESSENTIAL ONLY",
    )

    left(
        printer,
        (
            f"{essential_runway.get('months', 0):.2f} "
            "MONTHS / "
            f"{essential_runway.get('days', 0)} DAYS"
        ),
    )

    # ====================================
    # QUICK SUMMARY
    # ====================================

    print_line(printer, "=")

    printer.set(bold=True)
    left(
        printer,
        "QUICK SUMMARY",
    )
    printer.set(bold=False)

    summary_lines = (
        finance_quick_summary(
            snapshot
        )
    )

    for summary in summary_lines:

        print_wrapped(
            printer,
            printer_safe_text(
                summary
            ),
            width=40,
        )

    print_line(printer, "=")

def calculate_month_cashflow(
    transactions,
):
    today = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    ).date()

    income = 0.0
    outgoings = 0.0

    categories = {}

    for transaction in (
        transactions or []
    ):
        tx_date = transaction_date(
            transaction
        )

        if not tx_date:
            continue

        if (
            tx_date.year != today.year
            or tx_date.month
            != today.month
        ):
            continue

        amount = transaction_amount(
            transaction
        )

        if amount > 0:
            income += amount

        elif amount < 0:
            spent = abs(amount)

            outgoings += spent

            category = (
                categorise_transaction(
                    transaction
                )
            )

            categories[category] = (
                categories.get(
                    category,
                    0.0,
                )
                + spent
            )

    return {
        "income": income,
        "outgoings": outgoings,
        "net": income - outgoings,
        "categories": categories,
    }

def _safe_amount(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def calculate_financial_runway(
    balances,
    direct_debits=None,
    standing_orders=None,
    subscriptions=None,
    spending_summary=None,
):
    direct_debits = direct_debits or []
    standing_orders = standing_orders or []
    subscriptions = subscriptions or []
    spending_summary = spending_summary or {}

    hsbc = balances.get("HSBC", {})
    monzo = balances.get("MONZO", {})
    amex = balances.get("AMEX", {})

    amex = balances.get(
        "AMEX",
        {},
    )

    # Convert HSBC balance object to a number.
    if isinstance(hsbc, dict):
        hsbc_available = _safe_amount(
            hsbc.get(
                "available",
                hsbc.get(
                    "current",
                    0.0,
                ),
            )
        )
    else:
        hsbc_available = _safe_amount(
            hsbc
        )

    # Convert Monzo balance object to a number.
    if isinstance(monzo, dict):
        monzo_available = _safe_amount(
            monzo.get(
                "available",
                monzo.get(
                    "current",
                    0.0,
                ),
            )
        )
    else:
        monzo_available = _safe_amount(
            monzo
        )

    # For Amex, current is the amount owed.
    if isinstance(amex, dict):
        amex_owed = _safe_amount(
            amex.get(
                "current",
                0.0,
            )
        )
    else:
        amex_owed = _safe_amount(
            amex
        )

    dd_total = sum(
        _safe_amount(x.get("amount"))
        for x in direct_debits
    )
    so_total = sum(
        _safe_amount(x.get("amount"))
        for x in standing_orders
    )
    sub_total = sum(
        _safe_amount(x.get("amount"))
        for x in subscriptions
    )

    cash = hsbc_available + monzo_available
    net_cash = cash - amex_owed
    committed = dd_total + so_total + sub_total
    spendable = cash - committed - amex_owed

    normal_burn = _safe_amount(
        spending_summary.get("normal_monthly_burn", 0)
    )
    essential_burn = _safe_amount(
        spending_summary.get("essential_monthly_burn", 0)
    )

    normal_days = (
        max(net_cash, 0) / normal_burn * 30.44
        if normal_burn > 0 else 0
    )
    survival_days = (
        max(net_cash, 0) / essential_burn * 30.44
        if essential_burn > 0 else 0
    )

    return {
        "hsbc": hsbc_available,
        "monzo": monzo_available,
        "amex": amex_owed,
        "cash": cash,
        "net_cash": net_cash,
        "committed": committed,
        "spendable": spendable,
        "normal_burn": normal_burn,
        "essential_burn": essential_burn,
        "normal_days": normal_days,
        "survival_days": survival_days,
        "dd_total": dd_total,
        "so_total": so_total,
        "sub_total": sub_total,
    }


def _runway_bar(days, width=30, max_days=120):
    filled = int(
        max(0, min(days / max_days, 1)) * width
    )
    return (
        "[" + "#" * filled
        + "." * (width - filled) + "]"
    )


def print_full_finance_report(
    printer,
    balances,
    direct_debits=None,
    standing_orders=None,
    subscriptions=None,
    spending_summary=None,
):
    direct_debits = direct_debits or []
    standing_orders = standing_orders or []
    subscriptions = subscriptions or []
    spending_summary = spending_summary or {}

    s = calculate_financial_runway(
        balances,
        direct_debits,
        standing_orders,
        subscriptions,
        spending_summary,
    )

    salary_30 = _safe_amount(
        spending_summary.get("salary_30_days")
    )
    other_in_30 = _safe_amount(
        spending_summary.get("other_incoming_30_days")
    )
    total_in_30 = _safe_amount(
        spending_summary.get("total_incoming_30_days")
    )
    last_30 = _safe_amount(
        spending_summary.get("last_30_days")
    )
    net_flow_30 = _safe_amount(
        spending_summary.get("net_flow_30_days")
    )
    ninety_avg = _safe_amount(
        spending_summary.get("ninety_day_average")
    )
    essential_avg = _safe_amount(
        spending_summary.get("essential_monthly_burn")
    )

    trend_pct = 0.0
    if ninety_avg > 0 and last_30 > 0:
        trend_pct = (
            (last_30 - ninety_avg)
            / ninety_avg
            * 100.0
        )

    print_line(printer, "=")

    printer.set(bold=True)
    centre(printer, "FINANCE CHECK")
    printer.set(bold=False)

    left(printer, "ALL VALUES GBP")

    print_line(printer, "-")
    left(printer, "SNAPSHOT")
    left(printer, f"HSBC             {s['hsbc']:>10.2f}")
    left(printer, f"MONZO             {s['monzo']:>10.2f}")
    left(printer, f"CASH              {s['cash']:>10.2f}")
    left(printer, f"AMEX OWED         {-s['amex']:>10.2f}")
    left(printer, f"NET CASH          {s['net_cash']:>10.2f}")

    print_line(printer, "-")
    left(printer, "CASH FLOW / 30 DAYS")
    left(printer, f"SALARY            {salary_30:>10.2f}")
    left(printer, f"OTHER IN          {other_in_30:>10.2f}")
    left(printer, f"TOTAL IN          {total_in_30:>10.2f}")
    left(printer, f"SPENDING          {-last_30:>10.2f}")
    left(printer, f"NET FLOW          {net_flow_30:>+10.2f}")

    other_incomings = spending_summary.get(
        "other_incomings",
        []
    )

    if other_incomings:
        print_line(printer, "-")
        left(printer, "OTHER IN")

        for item in other_incomings[:5]:
            date_text = item["date"].strftime(
                "%d %b"
            ).upper()
            name = printer_safe_text(
                item.get(
                    "name",
                    "INCOMING PAYMENT",
                )
            )[:18]

            left(
                printer,
                (
                    f"{date_text} "
                    f"{name:<18} "
                    f"{item['amount']:>8.2f}"
                ),
            )

    if (
        direct_debits
        or standing_orders
        or subscriptions
    ):
        print_line(printer, "-")
        left(printer, "REGULAR OUTGOINGS")

        for item, label in (
            [(x, "DD") for x in direct_debits]
            + [(x, "SO") for x in standing_orders]
            + [(x, "SUB") for x in subscriptions]
        ):
            name = printer_safe_text(
                str(
                    item.get(
                        "name",
                        "PAYMENT",
                    )
                )
            )[:20]

            amount = _safe_amount(
                item.get("amount")
            )

            left(
                printer,
                (
                    f"{label:<3} "
                    f"{name:<20} "
                    f"{amount:>8.2f}"
                ),
            )

        left(
            printer,
            f"REGULAR TOTAL     {s['committed']:>10.2f}"
        )

    print_line(printer, "-")
    left(printer, "SPENDING")
    left(printer, f"90 DAY AVG        {ninety_avg:>10.2f}")
    left(printer, f"ESSENTIAL AVG     {essential_avg:>10.2f}")
    left(printer, f"LAST 30 DAYS      {last_30:>10.2f}")
    left(printer, f"TREND             {trend_pct:>9.1f}%")

    print_line(printer, "-")
    left(printer, "RUNWAY")

    normal_days = s["normal_days"]
    survival_days = s["survival_days"]

    left(printer, "NORMAL")
    left(printer, _runway_bar(normal_days))
    left(
        printer,
        (
            f"{normal_days:>5.0f} DAYS / "
            f"{normal_days / 30.44:>.1f} MO"
        ),
    )

    left(printer, "SURVIVAL")
    left(printer, _runway_bar(survival_days))
    left(
        printer,
        (
            f"{survival_days:>5.0f} DAYS / "
            f"{survival_days / 30.44:>.1f} MO"
        ),
    )

    print_line(printer, "=")
    left(printer, "SUMMARY")
    left(printer, f"NET CASH          {s['net_cash']:>10.2f}")
    left(printer, f"30D NET FLOW      {net_flow_30:>+10.2f}")
    left(
        printer,
        f"NORMAL RUNWAY     {normal_days:>7.0f} DAYS"
    )
    left(
        printer,
        f"SURVIVAL RUNWAY   {survival_days:>7.0f} DAYS"
    )

    print_line(printer, "-")

    if direct_debits:
        left(printer, "DD  DIRECT DEBIT")

    if standing_orders:
        left(printer, "SO  STANDING ORDER")

    if subscriptions:
        left(printer, "SUB EST. SUBSCRIPTION")

    if spending_summary.get("salary_incomings"):
        left(printer, "SAL LIKELY SALARY")

    print_wrapped(
        printer,
        (
            "RUNWAY BASED ON CURRENT NET CASH "
            "AND RECENT SPENDING."
        ),
        width=40,
    )

    print_line(printer, "=")


def _truelayer_account_ids(access_token):
    payload = _truelayer_get(
        access_token,
        "/accounts",
    )

    return [
        item.get("account_id")
        for item in payload.get("results", [])
        if item.get("account_id")
    ]


def _truelayer_card_ids(access_token):
    payload = _truelayer_get(
        access_token,
        "/cards",
    )

    return [
        item.get("account_id")
        for item in payload.get("results", [])
        if item.get("account_id")
    ]


def _truelayer_transactions(
    access_token,
    endpoint_prefix,
    account_id,
    from_date,
    to_date,
):
    response = requests.get(
        (
            f"{TRUELAYER_DATA_URL}/"
            f"{endpoint_prefix}/{account_id}/transactions"
        ),
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        params={
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        },
        timeout=20,
    )
    response.raise_for_status()

    return response.json().get("results", [])


def _truelayer_regular_payments(
    access_token,
    account_id,
    payment_type,
):
    payload = _truelayer_get(
        access_token,
        f"/accounts/{account_id}/{payment_type}",
    )

    return payload.get("results", [])


def _normalise_regular_payment(item, kind):
    """
    Convert TrueLayer DD/SO payloads into the compact format used
    by the receipt.
    """
    name = (
        item.get("name")
        or item.get("reference")
        or item.get("description")
        or "PAYMENT"
    )

    amount = _safe_amount(
        item.get("amount")
        or item.get("previous_payment_amount")
        or item.get("first_payment_amount")
    )

    return {
        "name": printer_safe_text(str(name)),
        "amount": abs(amount),
        "type": kind,
    }


def _transaction_name(tx):
    return printer_safe_text(
        str(
            tx.get("merchant_name")
            or tx.get("description")
            or "UNKNOWN"
        )
    )


def _transaction_date(tx):
    timestamp = tx.get("timestamp", "")

    if not timestamp:
        return None

    try:
        return datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        ).date()
    except ValueError:
        try:
            return datetime.strptime(
                timestamp[:10],
                "%Y-%m-%d",
            ).date()
        except ValueError:
            return None


def _is_outgoing_transaction(tx):
    amount = _safe_amount(tx.get("amount"))
    tx_type = str(
        tx.get("transaction_type", "")
    ).upper()

    return (
        amount < 0
        or tx_type == "DEBIT"
    )


def _transaction_spend_amount(tx):
    return abs(
        _safe_amount(
            tx.get("amount")
        )
    )


def _subscription_key(tx):
    """
    Use merchant name when available; otherwise description.
    """
    return _transaction_name(tx).strip().upper()


def infer_subscriptions(transactions):
    """
    Infer likely monthly recurring card/account subscriptions from
    transaction history.

    Criteria:
      - outgoing transactions only
      - same merchant/description
      - at least two occurrences
      - similar amounts
      - recurring intervals roughly 20-40 days
    """
    grouped = {}

    for tx in transactions:
        if not _is_outgoing_transaction(tx):
            continue

        date_value = _transaction_date(tx)
        amount = _transaction_spend_amount(tx)
        key = _subscription_key(tx)

        if not key or not date_value or amount <= 0:
            continue

        grouped.setdefault(key, []).append(
            {
                "date": date_value,
                "amount": amount,
            }
        )

    subscriptions = []

    for merchant, records in grouped.items():
        if len(records) < FINANCE_SUBSCRIPTION_MIN_OCCURRENCES:
            continue

        records.sort(
            key=lambda x: x["date"]
        )

        amounts = [
            item["amount"]
            for item in records
        ]

        average_amount = (
            sum(amounts) / len(amounts)
        )

        if average_amount <= 0:
            continue

        if any(
            abs(amount - average_amount)
            / average_amount
            > FINANCE_SUBSCRIPTION_AMOUNT_TOLERANCE
            for amount in amounts
        ):
            continue

        intervals = [
            (records[i]["date"] - records[i - 1]["date"]).days
            for i in range(1, len(records))
        ]

        monthly_intervals = [
            days
            for days in intervals
            if (
                FINANCE_SUBSCRIPTION_MIN_DAYS
                <= days
                <= FINANCE_SUBSCRIPTION_MAX_DAYS
            )
        ]

        if not monthly_intervals:
            continue

        subscriptions.append({
            "name": merchant.title(),
            "amount": round(
                average_amount,
                2,
            ),
            "type": "SUB",
        })

    subscriptions.sort(
        key=lambda item: item["amount"],
        reverse=True,
    )

    return subscriptions


def _transaction_classification_text(tx):
    parts = []

    merchant = tx.get("merchant_name")
    description = tx.get("description")
    classification = tx.get(
        "transaction_classification",
        [],
    )

    if merchant:
        parts.append(str(merchant))

    if description:
        parts.append(str(description))

    if isinstance(classification, list):
        parts.extend(
            str(x)
            for x in classification
        )

    return " ".join(parts).lower()


def _is_essential_transaction(tx):
    text = _transaction_classification_text(tx)

    return any(
        keyword in text
        for keyword in FINANCE_ESSENTIAL_KEYWORDS
    )


def _monthlyised_spend(
    transactions,
    days,
    essential_only=False,
):
    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    cutoff = today - timedelta(days=days)

    total = 0.0

    for tx in transactions:
        if not _is_outgoing_transaction(tx):
            continue

        tx_date = _transaction_date(tx)

        if not tx_date or tx_date < cutoff:
            continue

        if essential_only and not _is_essential_transaction(tx):
            continue

        total += _transaction_spend_amount(tx)

    if days <= 0:
        return 0.0

    return total / days * 30.44


def _last_n_day_spend(
    transactions,
    days,
):
    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    cutoff = today - timedelta(days=days)

    return sum(
        _transaction_spend_amount(tx)
        for tx in transactions
        if (
            _is_outgoing_transaction(tx)
            and _transaction_date(tx)
            and _transaction_date(tx) >= cutoff
        )
    )


def _dedupe_regular_payments(items):
    seen = set()
    result = []

    for item in items:
        key = (
            item.get("name", "").strip().upper(),
            round(
                _safe_amount(item.get("amount")),
                2,
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def _dedupe_subscriptions_against_regular(
    subscriptions,
    direct_debits,
    standing_orders,
):
    """
    Prevent an inferred subscription from being counted again when
    the same merchant/amount is already represented as a confirmed
    DD or SO.
    """
    regular = {
        (
            item.get("name", "").strip().upper(),
            round(
                _safe_amount(item.get("amount")),
                2,
            ),
        )
        for item in (
            direct_debits
            + standing_orders
        )
    }

    return [
        item
        for item in subscriptions
        if (
            item.get("name", "").strip().upper(),
            round(
                _safe_amount(item.get("amount")),
                2,
            ),
        )
        not in regular
    ]


def _is_incoming_transaction(tx):
    amount = _safe_amount(tx.get("amount"))
    tx_type = str(tx.get("transaction_type", "")).upper()
    tx_category = str(
        tx.get("transaction_category", "")
    ).upper()

    return (
        amount > 0
        or tx_type == "CREDIT"
        or tx_category == "CREDIT"
    )


def _incoming_transaction_name(tx):
    return printer_safe_text(
        str(
            tx.get("merchant_name")
            or tx.get("description")
            or "INCOMING PAYMENT"
        )
    )


def _looks_like_internal_transfer(tx):
    text = " ".join(
        [
            str(tx.get("description", "")),
            str(tx.get("merchant_name", "")),
            str(tx.get("transaction_category", "")),
        ]
    ).lower()

    return any(
        keyword in text
        for keyword in FINANCE_INTERNAL_TRANSFER_KEYWORDS
    )


def _looks_like_salary(tx):
    text = " ".join(
        [
            str(tx.get("description", "")),
            str(tx.get("merchant_name", "")),
        ]
    ).lower()

    return any(
        keyword in text
        for keyword in FINANCE_SALARY_KEYWORDS
    )


def analyse_incoming_payments(transactions):
    salary = []
    other = []

    for tx in transactions:
        if not _is_incoming_transaction(tx):
            continue

        if _looks_like_internal_transfer(tx):
            continue

        tx_date = _transaction_date(tx)
        amount = abs(
            _safe_amount(tx.get("amount"))
        )

        if not tx_date or amount <= 0:
            continue

        item = {
            "name": _incoming_transaction_name(tx),
            "amount": amount,
            "date": tx_date,
        }

        if _looks_like_salary(tx):
            salary.append(item)
        else:
            other.append(item)

    salary.sort(
        key=lambda item: item["date"],
        reverse=True,
    )
    other.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    return salary, other


def _incoming_total(items, days=None):
    if days is None:
        return sum(
            _safe_amount(item.get("amount"))
            for item in items
        )

    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    cutoff = today - timedelta(days=days)

    return sum(
        _safe_amount(item.get("amount"))
        for item in items
        if item.get("date")
        and item["date"] >= cutoff
    )

def get_truelayer_transactions(
    access_token,
    months=6,
):
    """
    Fetch transaction history for all TrueLayer
    current accounts using an existing access token.

    Returns one combined list of transactions.
    """

    import requests

    transactions = []

    headers = {
        "Authorization": (
            f"Bearer {access_token}"
        ),
        "Accept": "application/json",
    }

    base_url = (
        "https://api.truelayer.com"
    )

    # ------------------------------------
    # GET ACCOUNTS
    # ------------------------------------

    try:
        response = requests.get(
            f"{base_url}/data/v1/accounts",
            headers=headers,
            timeout=20,
        )

        response.raise_for_status()

        accounts = (
            response.json()
            .get(
                "results",
                [],
            )
        )

    except Exception as error:
        print(
            "Transaction account error:",
            repr(error),
        )
        return []

    # ------------------------------------
    # DATE RANGE
    # ------------------------------------

    end_date = datetime.now(
        ZoneInfo(
            "Europe/London"
        )
    )

    start_date = (
        end_date
        - timedelta(
            days=months * 31
        )
    )

    # ------------------------------------
    # GET TRANSACTIONS
    # ------------------------------------

    for account in accounts:

        account_id = account.get(
            "account_id"
        )

        if not account_id:
            continue

        try:
            response = requests.get(
                (
                    f"{base_url}/data/v1/"
                    f"accounts/{account_id}/"
                    "transactions"
                ),
                headers=headers,
                params={
                    "from": (
                        start_date
                        .strftime(
                            "%Y-%m-%dT00:00:00Z"
                        )
                    ),
                    "to": (
                        end_date
                        .strftime(
                            "%Y-%m-%dT23:59:59Z"
                        )
                    ),
                },
                timeout=20,
            )

            response.raise_for_status()

            account_transactions = (
                response.json()
                .get(
                    "results",
                    [],
                )
            )

            # Add account information so we know
            # where each transaction came from.
            for transaction in (
                account_transactions
            ):
                transaction[
                    "_account_id"
                ] = account_id

                transaction[
                    "_account_name"
                ] = account.get(
                    "display_name",
                    "ACCOUNT",
                )

                transactions.append(
                    transaction
                )

        except Exception as error:
            print(
                (
                    "Transaction fetch error "
                    f"for {account_id}:"
                ),
                repr(error),
            )

    return transactions

def get_regular_finance_data():
    """
    Retrieve live regular-payment and transaction information from
    TrueLayer for HSBC, Monzo and Amex.

    Returns:
      all_transactions
      direct_debits
      standing_orders
      inferred subscriptions
      spending_summary

    HSBC + Monzo are treated as bank accounts.
    Amex is treated as a credit card.
    """
    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    from_date = (
        today
        - timedelta(
            days=FINANCE_TRANSACTION_LOOKBACK_DAYS
        )
    )

    direct_debits = []
    standing_orders = []
    all_transactions = []

    provider_tokens = {}

    for provider in (
            "HSBC",
            "MONZO",
            "AMEX",
    ):
        try:
            provider_tokens[provider] = (
                _refresh_truelayer_access_token(
                    provider,
                    _initial_truelayer_refresh_token(
                        provider
                    ),
                )
            )

        except Exception as error:
            print(
                f"{provider} unavailable:",
                repr(error),
            )

            provider_tokens[provider] = None

    # Bank accounts: transactions, DDs and standing orders.
    for provider in ("HSBC", "MONZO"):
        access_token = provider_tokens.get(
            provider
        )

        if not access_token:
            continue

        for account_id in _truelayer_account_ids(
            access_token
        ):
            try:
                dd_items = _truelayer_regular_payments(
                    access_token,
                    account_id,
                    "direct_debits",
                )

                direct_debits.extend(
                    _normalise_regular_payment(
                        item,
                        "DD",
                    )
                    for item in dd_items
                )
            except requests.RequestException as error:
                print(
                    f"{provider} direct-debit error:",
                    error,
                )

            try:
                so_items = _truelayer_regular_payments(
                    access_token,
                    account_id,
                    "standing_orders",
                )

                standing_orders.extend(
                    _normalise_regular_payment(
                        item,
                        "SO",
                    )
                    for item in so_items
                )
            except requests.RequestException as error:
                print(
                    f"{provider} standing-order error:",
                    error,
                )

            try:
                all_transactions.extend(
                    _truelayer_transactions(
                        access_token,
                        "accounts",
                        account_id,
                        from_date,
                        today,
                    )
                )
            except requests.RequestException as error:
                print(
                    f"{provider} transaction error:",
                    error,
                )

    # Credit card: transaction history for subscription/spending
    # analysis. Direct-debit/standing-order endpoints are account-only.
    amex_token = provider_tokens.get(
        "AMEX"
    )

    if amex_token:

        for card_id in _truelayer_card_ids(
            amex_token
        ):
            try:
                all_transactions.extend(
                    _truelayer_transactions(
                        amex_token,
                        "cards",
                        card_id,
                        from_date,
                        today,
                    )
                )
            except requests.RequestException as error:
                print(
                    "AMEX transaction error:",
                    error,
                )

    direct_debits = _dedupe_regular_payments(
        direct_debits
    )

    standing_orders = _dedupe_regular_payments(
        standing_orders
    )

    subscriptions = infer_subscriptions(
        all_transactions
    )

    subscriptions = _dedupe_subscriptions_against_regular(
        subscriptions,
        direct_debits,
        standing_orders,
    )

    ninety_day_average = _monthlyised_spend(
        all_transactions,
        FINANCE_TRANSACTION_LOOKBACK_DAYS,
        essential_only=False,
    )

    essential_monthly_burn = _monthlyised_spend(
        all_transactions,
        FINANCE_TRANSACTION_LOOKBACK_DAYS,
        essential_only=True,
    )

    last_30_days = _last_n_day_spend(
        all_transactions,
        30,
    )

    salary_incomings, other_incomings = (
        analyse_incoming_payments(
            all_transactions
        )
    )

    salary_30 = _incoming_total(
        salary_incomings,
        days=30,
    )
    other_30 = _incoming_total(
        other_incomings,
        days=30,
    )
    total_incoming_30 = salary_30 + other_30
    net_flow_30 = (
        total_incoming_30
        - last_30_days
    )

    spending_summary = {
        "normal_monthly_burn": ninety_day_average,
        "essential_monthly_burn": essential_monthly_burn,
        "last_30_days": last_30_days,
        "ninety_day_average": ninety_day_average,
        "salary_incomings": salary_incomings,
        "other_incomings": other_incomings,
        "salary_30_days": salary_30,
        "other_incoming_30_days": other_30,
        "total_incoming_30_days": total_incoming_30,
        "net_flow_30_days": net_flow_30,
    }

    print(
        "DIRECT DEBITS:",
        repr(direct_debits),
    )

    print(
        "STANDING ORDERS:",
        repr(standing_orders),
    )

    return (
        all_transactions,
        direct_debits,
        standing_orders,
        subscriptions,
        spending_summary,
    )


def _strip_html_text(value):
    value = unescape(value or "")
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I|re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I|re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())

def _compact_news_summary(text, max_words=55):
    text = _strip_html_text(text)
    if not text:
        return ""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if len(x.split()) >= 6]
    words, out = 0, []
    for sentence in sentences[:4]:
        room = max_words - words
        if room <= 0: break
        sw = sentence.split()
        if len(sw) > room:
            sentence = " ".join(sw[:room]).rstrip(",;:-") + "..."
            sw = sentence.split()
        out.append(sentence); words += len(sw)
        if words >= 35: break
    return printer_safe_text(" ".join(out))

def _normalise_news_text(text):
    """
    Normalise news text so near-duplicate stories can be compared.
    """
    text = printer_safe_text(text or "").lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    text = re.sub(
        r"^(breaking|live|update|latest)\s+",
        "",
        text,
    )

    return text


def _news_text_similarity(first, second):
    first = _normalise_news_text(first)
    second = _normalise_news_text(second)

    if not first or not second:
        return 0.0

    return SequenceMatcher(
        None,
        first,
        second,
    ).ratio()


def _news_summary_is_useful(headline, summary):
    """
    Return False when the RSS description is basically
    just the headline repeated.
    """
    if not summary:
        return False

    headline_normalised = _normalise_news_text(
        headline
    )

    summary_normalised = _normalise_news_text(
        summary
    )

    if not summary_normalised:
        return False

    if headline_normalised == summary_normalised:
        return False

    # Summary contains too little additional information.
    if len(summary_normalised.split()) < 8:
        return False

    similarity = SequenceMatcher(
        None,
        headline_normalised,
        summary_normalised,
    ).ratio()

    if similarity >= 0.80:
        return False

    return True


def _news_items_are_duplicates(first, second):
    """
    Detect two headlines describing substantially the
    same story rather than only exact duplicate titles.
    """
    first_title = first.get("headline", "")
    second_title = second.get("headline", "")

    first_normalised = _normalise_news_text(
        first_title
    )

    second_normalised = _normalise_news_text(
        second_title
    )

    if not first_normalised or not second_normalised:
        return False

    if first_normalised == second_normalised:
        return True

    if _news_text_similarity(
        first_normalised,
        second_normalised,
    ) >= 0.78:
        return True

    first_words = set(
        first_normalised.split()
    )

    second_words = set(
        second_normalised.split()
    )

    if not first_words or not second_words:
        return False

    overlap = (
        len(first_words & second_words)
        / min(
            len(first_words),
            len(second_words),
        )
    )

    return overlap >= 0.75


def _deduplicate_news_stories(stories):
    unique = []

    for story in stories:
        if any(
            _news_items_are_duplicates(
                story,
                existing,
            )
            for existing in unique
        ):
            continue

        unique.append(story)

    return unique

def _is_probably_non_uk_birmingham(story):
    """
    Reject stories which appear to concern Birmingham
    in the US rather than Birmingham, UK.
    """
    headline = str(
        story.get("headline", "")
        or ""
    )

    summary = str(
        story.get("summary", "")
        or ""
    )

    source = str(
        story.get("source", "")
        or ""
    )

    text = (
            headline
            + " "
            + summary
            + " "
            + source
    ).lower()

    # Explicit foreign Birmingham.
    if any(
        signal in text
        for signal in NON_UK_BIRMINGHAM_SIGNALS
    ):
        return True

    # Dollar-denominated local-government stories are
    # a strong indication that this is not Birmingham UK.
    #
    # Only reject this way when there is no convincing
    # UK-local signal.
    if "$" in text:
        has_uk_signal = any(
            signal in text
            for signal in BIRMINGHAM_UK_SIGNALS
        )

        if not has_uk_signal:
            return True

    return False

def _score_birmingham_story(story):
    """
    Score a story according to how useful it is for a
    daily Birmingham receipt.

    This deliberately favours practical local information
    over sports commentary and clickbait.
    """
    headline = str(
        story.get("headline", "")
        or ""
    )

    summary = str(
        story.get("summary", "")
        or ""
    )

    source = str(
        story.get("source", "")
        or ""
    )

    text = (
            headline
            + " "
            + summary
            + " "
            + source
    ).lower()

    score = 0

    # -------------------------------------------------
    # WRONG BIRMINGHAM
    # -------------------------------------------------

    if _is_probably_non_uk_birmingham(
        story
    ):
        return -100

    # -------------------------------------------------
    # STRONG UK / LOCAL SIGNALS
    # -------------------------------------------------

    event_story = any(
        signal in text
        for signal in EVENT_SIGNALS
    )

    if event_story:
        # Events only receive a useful-news boost when
        # they are actually imminent.
        if (
                "today" in text
                or "tonight" in text
                or "tomorrow" in text
                or "this weekend" in text
        ):
            score += 2
        else:
            score -= 2

    immediate_matches = sum(
        1
        for signal in IMMEDIATE_LOCAL_SIGNALS
        if signal in text
    )

    score += min(
        immediate_matches * 5,
        10,
    )

    local_matches = sum(
        1
        for signal in BIRMINGHAM_UK_SIGNALS
        if signal in text
    )

    score += min(
        local_matches * 2,
        6,
    )

    # The story actually names Birmingham.
    if "birmingham" in text:
        score += 2

    # -------------------------------------------------
    # USEFUL LOCAL INFORMATION
    # -------------------------------------------------

    useful_matches = sum(
        1
        for signal in HIGH_VALUE_LOCAL_SIGNALS
        if signal in text
    )

    score += min(
        useful_matches * 2,
        8,
    )

    # -------------------------------------------------
    # LOW-VALUE / CLICKBAIT
    # -------------------------------------------------

    low_value_matches = sum(
        1
        for signal in LOW_VALUE_NEWS_SIGNALS
        if signal in text
    )

    score -= (
        low_value_matches * 4
    )

    # -------------------------------------------------
    # SPORT
    # -------------------------------------------------

    villa_story = (
        "aston villa" in text
        or "villa" in headline.lower()
    )

    birmingham_city_story = (
        "birmingham city" in text
        or "blues" in headline.lower()
    )

    # Routine football shouldn't dominate a general
    # Birmingham briefing.
    if villa_story:
        important_villa = any(
            signal in text
            for signal in IMPORTANT_VILLA_SIGNALS
        )

        if important_villa:
            score += 2
        else:
            score -= 4

    if birmingham_city_story:
        # Keep genuinely significant Blues news possible,
        # but heavily down-rank routine match coverage.
        if (
            "match report" in text
            or "player ratings" in text
            or "preview" in text
        ):
            score -= 6
        else:
            score -= 2

    # Women's/youth routine match reports are valid news,
    # but not high-priority general local information.
    if (
        "women" in text
        and "match report" in text
    ):
        score -= 4

    return score

def _rank_birmingham_news(stories):
    ranked = []

    for story in stories:
        story = dict(story)

        score = _score_birmingham_story(
            story
        )

        story["local_score"] = score

        # Don't pad the receipt with weak stories.
        if score < LOCAL_NEWS_MIN_SCORE:
            continue

        ranked.append(
            story
        )

    # Primarily rank by usefulness.
    ranked.sort(
        key=lambda story: (
            story.get(
                "local_score",
                0,
            ),
            story.get(
                "published"
            )
            or datetime.min.replace(
                tzinfo=ZoneInfo(
                    "Europe/London"
                )
            ),
        ),
        reverse=True,
    )

    return ranked

def _news_stories(
    url,
    number=3,
    params=None,
    max_age_hours=None,
):
    response = requests.get(
        url,
        params=params,
        timeout=15,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; ReceiptNews/2.0)"
            )
        },
    )

    response.raise_for_status()

    root = ET.fromstring(
        response.content
    )

    now = datetime.now(
        ZoneInfo("Europe/London")
    )

    stories = []

    for item in root.findall(
        "./channel/item"
    ):
        title_el = item.find("title")
        desc_el = item.find("description")
        date_el = item.find("pubDate")

        if (
            title_el is None
            or not title_el.text
        ):
            continue

        title = printer_safe_text(
            " ".join(
                title_el.text.split()
            )
        )

        source = ""

        if " - " in title:
            title, source = title.rsplit(
                " - ",
                1,
            )

            title = title.strip()
            source = source.strip()

        # -----------------------------
        # PUBLICATION AGE
        # -----------------------------

        published = None

        if (
            date_el is not None
            and date_el.text
        ):
            try:
                published = (
                    parsedate_to_datetime(
                        date_el.text
                    )
                    .astimezone(
                        ZoneInfo(
                            "Europe/London"
                        )
                    )
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                published = None

        if (
            max_age_hours is not None
            and published is not None
        ):
            age_hours = (
                now - published
            ).total_seconds() / 3600

            if (
                age_hours < 0
                or age_hours > max_age_hours
            ):
                continue

        # -----------------------------
        # SUMMARY
        # -----------------------------

        description = (
            desc_el.text
            if (
                desc_el is not None
                and desc_el.text
            )
            else ""
        )

        summary = _compact_news_summary(
            description
        )

        # Don't print a second copy of the
        # headline as the article body.
        if not _news_summary_is_useful(
            title,
            summary,
        ):
            summary = ""

        stories.append({
            "headline": title,
            "summary": summary,
            "published": published,
            "source": source,
        })

        # Fetch a larger candidate pool.
        if len(stories) >= number:
            break

    return stories

def get_top_news_headlines(number=3):
    return _news_stories(NEWS_RSS_URL, number)

def get_birmingham_news_headlines(
    number=5,
):
    """
    Return up to `number` genuinely useful Birmingham
    stories for the daily receipt.

    It is deliberately acceptable to return fewer than
    `number` stories when the available news is poor.
    """

    collected = []

    # Fetch far more stories than we ultimately print.
    # Filtering/ranking happens afterwards.
    candidates_per_query = 12

    for query in LOCAL_NEWS_QUERIES:

        try:
            stories = _news_stories(
                LOCAL_NEWS_RSS_URL,
                candidates_per_query,
                {
                    "q": query,
                    "hl": "en-GB",
                    "gl": "GB",
                    "ceid": "GB:en",
                },

                # Daily briefing should contain recent
                # material rather than old search results.
                max_age_hours=48,
            )

            collected.extend(
                stories
            )

        except Exception as error:
            print(
                "Local news query error:",
                query,
                repr(error),
            )

    # -------------------------------------------------
    # REMOVE DUPLICATE COVERAGE
    # -------------------------------------------------

    unique = _deduplicate_news_stories(
        collected
    )

    # -------------------------------------------------
    # SCORE FOR ACTUAL USEFULNESS
    # -------------------------------------------------

    ranked = _rank_birmingham_news(
        unique
    )

    # -------------------------------------------------
    # DEBUG
    # -------------------------------------------------
    #
    # Keep this temporarily. It will make tuning the
    # scoring system much easier.
    #

    print(
        "\n=== BIRMINGHAM NEWS RANKING ==="
    )

    for story in sorted(
        unique,
        key=_score_birmingham_story,
        reverse=True,
    )[:20]:

        print(
            f"{_score_birmingham_story(story):>4} | "
            f"{story.get('headline', '')}"
        )

    print(
        "================================\n"
    )

    # Crucially: DO NOT fill empty positions with
    # low-quality stories.
    return ranked[:number]

def _print_news_stories(
    printer,
    heading,
    stories,
):
    if not stories:
        return

    print_line(
        printer,
        "=",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        heading,
    )

    printer.set(
        bold=False
    )

    for index, story in enumerate(
        stories[:5],
        1,
    ):
        if index > 1:
            printer.text("\n")

        headline = story.get(
            "headline",
            "",
        )

        summary = story.get(
            "summary",
            "",
        )

        print_wrapped(
            printer,
            f"{index}. {headline}",
            width=40,
        )

        if _news_summary_is_useful(
            headline,
            summary,
        ):
            print_wrapped(
                printer,
                summary,
                width=40,
            )

def print_news(printer, stories):
    _print_news_stories(printer, "UK NEWS", stories)

def print_local_news(printer, stories):
    _print_news_stories(printer, "BIRMINGHAM NEWS", stories)

# ============================================================
# COMPACT PRINTER HELPERS
# ============================================================

def setup_printer(printer):
    """Use compact standard ESC/POS text throughout."""

    printer.hw("init")
    printer.set(
        font="a",
        bold=False,
        double_height=False,
        double_width=False,
        align="left",
    )

def print_line(printer, character="-"):
    printer_text(printer, character * RECEIPT_WIDTH + "\n")

def centre(printer, text):
    printer.set(align="center")
    printer_text(printer, text + "\n")

def left(printer, text):
    printer.set(align="left")
    printer_text(printer, text + "\n")

def boxed_line(printer, text):
    """Compact boxed line with no unnecessary padding."""

    available = RECEIPT_WIDTH - 2
    text = text.replace("\n", " ")[:available]
    printer_text(printer, "|" + text.ljust(available) + "|\n")


def print_wrapped(printer, text, width=40):
    """Wrap text to fit the compact receipt width."""

    words = text.split()
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            if line:
                left(printer, line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        left(printer, line)

# ============================================================
# COMPACT TEMPERATURE GRAPH
# ============================================================

def print_temperature_graph(printer, readings):
    """
    Print a compact monochrome stepped-line temperature graph.

    The six four-hour readings are connected using horizontal
    steps with vertical transitions. This gives the receipt a
    vintage weather-station / chart-recorder appearance while
    remaining a bitmap, so no Unicode graph characters are sent
    to the ESC/POS printer.
    """

    if not readings:
        return
    temperatures = [
        r["temperature"]
        for r in readings
    ]
    graph_min = int(min(temperatures)) - 1
    graph_max = int(max(temperatures)) + 1
    if graph_min == graph_max:
        graph_max += 1
    image_width = 500
    image_height = 190
    image = Image.new(
        "1",
        (image_width, image_height),
        1,
    )
    draw = ImageDraw.Draw(image)
    left_margin = 38
    right_margin = 10
    top_margin = 8
    bottom_margin = 28
    graph_width = (
        image_width
        - left_margin
        - right_margin
    )
    graph_height = (
        image_height
        - top_margin
        - bottom_margin
    )
    x_axis = top_margin + graph_height
    # Main axes.
    draw.line(
        (
            left_margin,
            top_margin,
            left_margin,
            x_axis,
        ),
        fill=0,
        width=1,
    )
    draw.line(
        (
            left_margin,
            x_axis,
            image_width - right_margin,
            x_axis,
        ),
        fill=0,
        width=1,
    )
    # Horizontal temperature reference lines.
    for step in range(4):
        value = (
            graph_min
            + (
                graph_max - graph_min
            ) * step / 3
        )
        y = int(
            x_axis
            - graph_height * step / 3
        )

        # Dotted-looking reference line.
        for x in range(
                left_margin,
                image_width - right_margin,
                8,
        ):
            draw.line(
                (
                    x,
                    y,
                    min(
                        x + 3,
                        image_width - right_margin,
                    ),
                    y,
                ),
                fill=0,
                width=1,
            )
            draw.text(
            (3, y - 5),
            f"{value:.0f}",
            fill=0,
        )
    count = len(readings)
    if count == 1:
        spacing = graph_width
    else:
        spacing = graph_width / (count - 1)
    points = []
    for index, reading in enumerate(readings):
        temperature = reading["temperature"]
        normalized = (
            temperature - graph_min
        ) / (
            graph_max - graph_min
        )
        x = int(
            left_margin
            + index * spacing
        )
        y = int(
            x_axis
            - normalized * graph_height
        )
        points.append((x, y))
        # Four-hour time labels.
        hour = int(
            reading["time"][:2]
        )
        if hour % 4 == 0:
            draw.text(
                (x - 7, x_axis + 6),
                reading["time"][:2],
                fill=0,
            )

    # Stepped trace:
    # horizontal at the old value, then vertical at the next
    # observation. A thicker line survives thermal printing well.
    if len(points) == 1:
        x, y = points[0]
        draw.line(
            (x - 8, y, x + 8, y),
            fill=0,
            width=3,
        )
    else:
        for index in range(
            len(points) - 1
        ):
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            draw.line(
                (x1, y1, x2, y1),
                fill=0,
                width=3,
            )
            draw.line(
                (x2, y1, x2, y2),
                fill=0,
                width=3,
            )

        # Small square markers make each actual observation clear.
        for x, y in points:
            draw.rectangle(
                (
                    x - 3,
                    y - 3,
                    x + 3,
                    y + 3,
                ),
                fill=0,
            )
    buffer = BytesIO()
    image.save(
        buffer,
        format="PNG",
    )
    buffer.seek(0)
    printer.image(buffer)
    printer_text(printer, "\n")

# ============================================================
# RECEIPT SECTIONS
# ============================================================

def print_header(printer):
    """Compact vintage machine-style header."""

    printer.set(
        align="center",
        font="a",
        bold=True,
        double_height=False,
        double_width=False,
    )
    printer_text(printer, "DAILY UPDATE\n")
    printer.set(bold=False)
    now = datetime.now()
    printer_text(printer,
        now.strftime("%a %d %b %Y  %H:%M:%S").upper()
        + "\n"
    )
    printer_text(printer,
        f"{LOCATION_NAME} / {LOCATION_REGION}\n"
    )

def _route_distance_text(option):
    metres = option.distance_metres
    if not metres:
        return ""
    miles = metres / 1609.344
    if miles < 0.1:
        return f"{metres:.0f} M"
    return f"{miles:.1f} MI"

def _right_value_line(
    printer,
    label,
    value,
    width=40,
):
    """
    Print a label on the left and a value flush-right.
    """
    label = str(label or "").strip()
    value = str(value or "").strip()

    available = (
        width
        - len(value)
        - 1
    )

    if len(label) > available:
        label = label[:available]

    left(
        printer,
        f"{label:<{available}} {value}",
    )


def _time_line(
    printer,
    label,
    dt,
    width=40,
):
    """
    Print a time consistently flush-right.
    """
    if not dt:
        return

    if hasattr(dt, "strftime"):
        value = dt.strftime("%H:%M")
    else:
        value = str(dt)

    _right_value_line(
        printer,
        label,
        value,
        width,
    )

def _public_transport_label(option):
    """
    Produce labels such as:

        BUS 45
        BUS X1
        TRAIN - BOURNVILLE
        TRAM WEST MIDLANDS METRO
    """

    for leg in option.transit_legs:

        mode = str(
            getattr(
                leg,
                "mode",
                "",
            )
            or ""
        ).upper()

        if mode == "WALK":
            continue

        route = str(
            getattr(
                leg,
                "route_name",
                "",
            )
            or ""
        ).strip()

        departure_stop = str(
            getattr(
                leg,
                "departure_stop",
                "",
            )
            or ""
        ).strip()

        # -----------------------------
        # BUS
        # -----------------------------

        if "BUS" in mode:

            if route:
                return (
                    f"BUS {route}"
                ).upper()

            return "BUS"

        # -----------------------------
        # TRAIN / RAIL
        # -----------------------------

        if (
            "TRAIN" in mode
            or "RAIL" in mode
        ):

            if departure_stop:
                station = re.sub(
                    r"\s+station$",
                    "",
                    departure_stop,
                    flags=re.IGNORECASE,
                )

                return (
                    f"TRAIN - {station}"
                ).upper()

            return "TRAIN"

        # -----------------------------
        # TRAM
        # -----------------------------

        if (
            "TRAM" in mode
            or "LIGHT_RAIL" in mode
        ):

            if route:
                return (
                    f"TRAM {route}"
                ).upper()

            return "TRAM"

        # Other public transport.
        if route:
            return (
                f"{mode} {route}"
            ).strip()

        if mode:
            return mode

    return "PUBLIC TRANSPORT"

def _public_transport_route(option):
    """
    Return a compact route description for the first
    non-walking public-transport leg.

    Examples:
        BUS 45
        TRAIN
        BOURNVILLE -> BIRMINGHAM NEW STREET
    """

    for leg in option.transit_legs:

        mode = str(
            getattr(
                leg,
                "mode",
                "",
            )
            or ""
        ).upper()

        if mode == "WALK":
            continue

        route = str(
            getattr(
                leg,
                "route_name",
                "",
            )
            or ""
        ).strip()

        departure_stop = str(
            getattr(
                leg,
                "departure_stop",
                "",
            )
            or ""
        ).strip()

        arrival_stop = str(
            getattr(
                leg,
                "arrival_stop",
                "",
            )
            or ""
        ).strip()

        # Remove redundant "Station" suffix on receipts.
        departure_stop = re.sub(
            r"\s+station$",
            "",
            departure_stop,
            flags=re.IGNORECASE,
        )

        arrival_stop = re.sub(
            r"\s+station$",
            "",
            arrival_stop,
            flags=re.IGNORECASE,
        )

        # -----------------------------
        # BUS
        # -----------------------------

        if "BUS" in mode:
            label = (
                f"BUS {route}"
                if route
                else "BUS"
            )

            return (
                label.upper(),
                "",
            )

        # -----------------------------
        # TRAIN
        # -----------------------------

        if (
            "TRAIN" in mode
            or "RAIL" in mode
        ):
            journey = ""

            if departure_stop and arrival_stop:
                journey = (
                    f"{departure_stop} -> "
                    f"{arrival_stop}"
                ).upper()

            return (
                "TRAIN",
                journey,
            )

        # -----------------------------
        # TRAM
        # -----------------------------

        if (
            "TRAM" in mode
            or "LIGHT_RAIL" in mode
        ):
            label = (
                f"TRAM {route}"
                if route
                else "TRAM"
            )

            return (
                label.upper(),
                "",
            )

        label = (
            f"{mode} {route}"
            if route
            else mode
        )

        return (
            label.upper(),
            "",
        )

    return (
        "PUBLIC TRANSPORT",
        "",
    )

def print_calendar(printer, events):
    """
    Print today's calendar as:

    1. A compact checklist of all events.
    2. A travel section containing useful journey
       information without turn-by-turn directions.

    The entire section is omitted when there are no events.
    """
    if not events:
        return

    # =================================================
    # CALENDAR OVERVIEW
    # =================================================

    print_line(
        printer,
        "=",
    )

    printer.set(
        bold=True
    )

    left(
        printer,
        "TODAY'S CALENDAR",
    )

    printer.set(
        bold=False
    )

    print_line(
        printer,
        "-",
    )

    # Quick checklist of every event.
    for event in events:
        time_text = (
            event.get("time")
            or ""
        )

        title = (
            event.get("title")
            or "EVENT"
        )

        print_wrapped(
            printer,
            f"[ ] {time_text}  {title}",
            width=40,
        )

    # =================================================
    # SETUP TRAVEL
    # =================================================

    home = private_value(
        "locations",
        "home",
    )

    api_key = private_value(
        "google_maps",
        "routes_api_key",
    )

    previous = None
    travel_started = False

    # =================================================
    # EVENT TRAVEL
    # =================================================

    for event in events:

        location = (
            event.get("location")
            or ""
        ).strip()

        # Ignore online events.
        online = any(
            marker in location.lower()
            for marker in (
                "zoom",
                "teams",
                "meet.google",
                "online",
                "virtual",
            )
        )

        # Only attempt travel for events where it
        # actually makes sense.
        if (
            not location
            or online
            or event.get("all_day")
            or not event.get("start_dt")
            or not home
            or not api_key
        ):
            previous = event
            continue

        origin, origin_label = (
            sensible_chained_origin(
                home=home,
                previous_event=previous,
                current_event=event,
            )
        )

        options = travel_options(
            api_key=api_key,
            origin=origin,
            destination=location,
            event_start=event["start_dt"],
            drive_buffer_minutes=10,
            transit_buffer_minutes=15,
            walk_buffer_minutes=10,
            show_walk_under_minutes=40,
        )

        if not options:
            previous = event
            continue

        # ---------------------------------------------
        # Start TRAVEL section only if at least one
        # event actually has journey information.
        # ---------------------------------------------

        if not travel_started:
            printer.text("\n")

            printer.set(
                bold=True
            )

            left(
                printer,
                "TRAVEL",
            )

            printer.set(
                bold=False
            )

            print_line(
                printer,
                "-",
            )

            travel_started = True

        else:
            # Exactly one separator between events.
            print_line(
                printer,
                "-",
            )

        # ---------------------------------------------
        # EVENT
        # ---------------------------------------------

        event_time = (
            event.get("time")
            or ""
        )

        # If time contains "13:00-14:00", only show
        # the start time in the travel section.
        start_time = (
            event_time.split(
                "-",
                1,
            )[0].strip()
        )

        title = (
            event.get("title")
            or "EVENT"
        ).upper()

        print_wrapped(
            printer,
            f"{start_time}  {title}",
            width=40,
        )

        print_wrapped(
            printer,
            location,
            width=40,
        )

        printer.text("\n")

        left(
            printer,
            f"FROM {origin_label.upper()}",
        )

        # ---------------------------------------------
        # PRIORITISE WALKING
        # ---------------------------------------------

        walk_option = next(
            (
                option
                for option in options
                if option.mode == "WALK"
            ),
            None,
        )

        display_options = list(
            options
        )

        if (
            walk_option
            and walk_option.duration_minutes <= 20
        ):
            display_options.remove(
                walk_option
            )

            display_options.insert(
                0,
                walk_option,
            )

        # ---------------------------------------------
        # JOURNEY OPTIONS
        # ---------------------------------------------

        first_option = True

        for option in display_options:

            if not first_option:
                printer.text("\n")

            first_option = False

            # =========================================
            # WALK / DRIVE
            # =========================================

            if option.mode != "TRANSIT":

                label = option.mode

                if (
                    option.mode == "WALK"
                    and option.duration_minutes <= 20
                ):
                    label = "WALK - RECOMMENDED"

                elif option.mode == "WALK":
                    label = "WALK"

                elif (
                    option.mode == "DRIVE"
                    and walk_option
                    and walk_option.duration_minutes <= 20
                ):
                    label = "DRIVE - ALTERNATIVE"

                _right_value_line(
                    printer,
                    label,
                    f"{option.duration_minutes} MIN",
                )

                distance = _route_distance_text(
                    option
                )

                if distance:
                    _right_value_line(
                        printer,
                        "DISTANCE",
                        distance.upper(),
                    )

                _time_line(
                    printer,
                    "LEAVE BY",
                    option.leave_by,
                )

                continue

            # =========================================
            # PUBLIC TRANSPORT
            # =========================================

            transport_label = (
                _public_transport_label(
                    option
                )
            )

            _right_value_line(
                printer,
                transport_label,
                f"{option.duration_minutes} MIN",
            )

            _time_line(
                printer,
                "LEAVE",
                option.leave_by,
            )

            _time_line(
                printer,
                "ARRIVE",
                option.arrive_by,
            )

            # -----------------------------------------
            # NO TURN-BY-TURN DIRECTIONS
            # -----------------------------------------
            #
            # We deliberately do NOT print:
            #
            # for leg in option.transit_legs:
            #     leg.instruction
            #
            # The receipt only needs journey timing.

            # -----------------------------------------
            # EARLIER SERVICES
            # -----------------------------------------

            if option.earlier_options:

                # Separate the recommended journey from
                # the alternative services.
                print_line(
                    printer,
                    "-",
                )

                left(
                    printer,
                    "EARLIER",
                )

                for earlier_index, earlier in enumerate(
                        option.earlier_options
                ):

                    # Blank line between earlier services,
                    # but no ----- separator.
                    printer.text("\n")

                    earlier_label, earlier_route = (
                        _public_transport_route(
                            earlier
                        )
                    )

                    # Service + duration.
                    _right_value_line(
                        printer,
                        earlier_label,
                        f"{earlier.duration_minutes} MIN",
                    )

                    # For trains, show stations.
                    if earlier_route:
                        print_wrapped(
                            printer,
                            earlier_route,
                            width=40,
                        )

                    _time_line(
                        printer,
                        "LEAVE",
                        earlier.leave_by,
                    )

                    _time_line(
                        printer,
                        "ARRIVE",
                        earlier.arrive_by,
                    )

        previous = event

def print_vehicle_expiry_checks(
    printer,
    vehicles,
    dvla_api_key,
):
    now = datetime.now(
        ZoneInfo("Europe/London")
    )

    # Monday = 0 ... Sunday = 6
    if now.weekday() != 6:
        return

    if not vehicles or not dvla_api_key:
        return

    vehicles_due = []

    for vehicle in vehicles:
        registration = vehicle.get(
            "registration"
        )

        name = vehicle.get(
            "name",
            registration,
        )

        try:
            status = get_vehicle_status(
                registration,
                dvla_api_key,
            )

            warnings = expiring_vehicle_items(
                status,
                today=now.date(),
                days=31,
            )

            if warnings:
                vehicles_due.append(
                    (
                        name,
                        status,
                        warnings,
                    )
                )

        except Exception as error:
            print(
                "Vehicle check error "
                f"({registration}): "
                f"{error!r}"
            )

    # Nothing expiring = absolutely no
    # receipt output.
    if not vehicles_due:
        return

    print_line(printer, "=")

    printer.set(bold=True)
    left(printer, "VEHICLE REMINDERS")
    printer.set(bold=False)

    for name, status, warnings in vehicles_due:
        print_line(printer, "-")

        registration = status[
            "registration"
        ]

        left(
            printer,
            printer_safe_text(
                f"{name} - {registration}"
            ),
        )

        for warning in warnings:
            expiry = warning[
                "expiry_date"
            ]

            remaining = warning[
                "days_remaining"
            ]

            left(
                printer,
                warning["type"],
            )

            left(
                printer,
                (
                    f"EXPIRES {expiry:%d %b %Y} "
                    f"- {remaining} DAYS"
                ).upper(),
            )

def therapy_payment_due(events):
    """Return True when an upcoming calendar event is a therapy appointment."""
    if not events:
        return False

    for event in events:
        if not isinstance(event, dict):
            continue

        title = str(
            event.get("title")
            or event.get("summary")
            or ""
        ).strip().lower()

        if "therapy" in title:
            return True

    return False

def print_google_doc(printer, text, upcoming_events):
    print_line(printer, "=")

    printer.set(bold=True)
    left(printer, "TO DO")
    printer.set(bold=False)
    print_line(printer, "-")

    # ----------------------------------------
    # AUTOMATIC THERAPY PAYMENT REMINDER
    # ----------------------------------------

    if therapy_payment_due(upcoming_events):
        print_wrapped(
            printer,
            f"[ ] {printer_safe_text('Pay for therapy')}",
            width=40,
        )

    for line in text.splitlines():
        line = line.lstrip('\ufeff').strip()

        # Only print lines ending with a full stop.
        if not line.endswith("."):
            continue

        # Remove the full stop before printing.
        line = line[:-1].strip()
        if not line:
            continue
        print_wrapped(
            printer,
            f"[ ] {printer_safe_text(line)}",
            width=40,
        )

def print_random_document_lines(printer, text):
    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, "EXERCISES TO DO")
    printer.set(bold=False)
    print_line(printer, "-")

    # .split() breaks the selected text into
    # individual exercises.
    words = get_random_lines(RANDOM_LINES).split()

    for word in words:
        print_wrapped(
            printer,
            f"[ ] {printer_safe_text(word)}",
            width=40,
        )

BORING_WEATHER_CODES = {0, 1, 2, 3}


def is_definitively_boring_weather(weather):
    """
    Return True only when every available signal says today's weather is mundane.

    This is intentionally conservative: uncertainty or any notable condition
    keeps the full weather output. Thresholds use the units requested from
    Open-Meteo (C, km/h, mm, metres).
    """
    try:
        hourly = weather["hourly"]
        daily = weather["daily"]

        temperatures = [float(x) for x in hourly.get("temperature_2m", []) if x is not None]
        winds = [float(x) for x in hourly.get("wind_speed_10m", []) if x is not None]
        gusts = [float(x) for x in hourly.get("wind_gusts_10m", []) if x is not None]
        precip_probs = [float(x) for x in hourly.get("precipitation_probability", []) if x is not None]
        precipitation = [float(x) for x in hourly.get("precipitation", []) if x is not None]
        visibility = [float(x) for x in hourly.get("visibility", []) if x is not None]
        codes = [int(x) for x in hourly.get("weather_code", []) if x is not None]

        # Missing inputs mean we cannot confidently call the day boring.
        if not all((temperatures, winds, gusts, precip_probs, precipitation, visibility, codes)):
            return False

        high = float(daily["temperature_2m_max"][0])
        low = float(daily["temperature_2m_min"][0])
        daily_rain_probability = float(daily["precipitation_probability_max"][0])

        return (
            all(code in BORING_WEATHER_CODES for code in codes)
            and max(precip_probs) < 20.0
            and daily_rain_probability < 20.0
            and sum(precipitation) < 0.2
            and max(winds) < 32.2       # 20 mph
            and max(gusts) < 48.3       # 30 mph
            and high < 25.0
            and low > 3.0
            and (high - low) < 10.0
            and min(visibility) >= 5000.0
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def print_compact_weather(printer, weather):
    current = weather["current"]
    daily = weather["daily"]
    condition = weather_description(current["weather_code"])
    high = float(daily["temperature_2m_max"][0])
    low = float(daily["temperature_2m_min"][0])

    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, "WEATHER")
    printer.set(bold=False)
    left(printer, f"{current['temperature_2m']:.1f}C  {condition}")
    left(printer, f"HIGH {high:.1f}C / LOW {low:.1f}C")
    left(printer, "DRY WITH LIGHT WINDS")


def print_weather(printer, weather):
    if is_definitively_boring_weather(weather):
        print_compact_weather(printer, weather)
        return

    current = weather["current"]
    daily = weather["daily"]

    # Detailed text stays at four-hour intervals.
    text_readings = get_hourly_weather(
        weather,
        interval_hours=4,
    )

    # Graph gets twice as much resolution.
    graph_readings = get_hourly_weather(
        weather,
        interval_hours=2,
    )

    print_line(printer, "=")
    printer.set(bold=True)
    centre(printer, "WEATHER")
    printer.set(bold=False)
    centre(printer, LOCATION_NAME)
    centre(printer, LOCATION_REGION)
    print_line(printer)

    # Compact current weather graphic.
    for line in weather_graphic(current["weather_code"]):
        centre(printer, line)
    current_temperature = current["temperature_2m"]
    current_condition = weather_description(
        current["weather_code"]
    )
    printer.set(bold=True)
    centre(
        printer,
        f"{current_temperature:.1f}C  {current_condition}",
    )
    printer.set(bold=False)
    print_line(printer)
    # Current conditions: two compact lines.
    printer.set(bold=True)
    left(printer, "CURRENT CONDITIONS")
    printer.set(bold=False)
    left(
        printer,
        f"TEMP {current_temperature:.1f}C"
        f"  FEELS {current['apparent_temperature']:.1f}C",
    )
    left(
        printer,
        f"HUM {current['relative_humidity_2m']:.0f}%"
        f"  WIND {current['wind_speed_10m']:.1f}km/h",
    )
    left(
        printer,
        f"PRESS {current['surface_pressure']:.0f}hPa"
        f"  DIR {current['wind_direction_10m']:.0f}deg",
    )

    # Four-hourly weather.
    print_line(printer)

    printer.set(bold=True)
    left(printer, "4-HOURLY WEATHER")
    printer.set(bold=False)

    for reading in text_readings:
        condition = weather_description(reading["code"])

        # Keep each reading compact.
        line = (
            f"{reading['time']} "
            f"{reading['temperature']:4.1f}C "
            f"{reading['humidity']:3.0f}% "
            f"{reading['wind']:4.1f}k "
            f"{condition}"
        )

        print_wrapped(
            printer,
            line,
            width=40,
        )

    # Temperature graph.
    print_line(printer)
    printer.set(bold=True)
    left(printer, "TEMPERATURE GRAPH")
    printer.set(bold=False)
    print_temperature_graph(
        printer,
        graph_readings,
    )

    # Daily summary.
    print_line(printer)
    printer.set(bold=True)
    left(printer, "TODAY")
    printer.set(bold=False)
    left(
        printer,
        f"MAX {daily['temperature_2m_max'][0]:.1f}C"
        f"  MIN {daily['temperature_2m_min'][0]:.1f}C",
    )
    left(
        printer,
        f"RAIN {daily['precipitation_probability_max'][0]:.0f}%",
    )
    sunrise = datetime.fromisoformat(
        daily["sunrise"][0]
    )
    sunset = datetime.fromisoformat(
        daily["sunset"][0]
    )
    left(
        printer,
        f"SUNSET/SUNRISE {sunrise.strftime('%H:%M')}"
        f"-{sunset.strftime('%H:%M')}",
    )

def should_print_subscriptions():
    """
    Subscriptions are printed every Sunday.
    """
    now = datetime.now(
        ZoneInfo("Europe/London")
    )
    return now.weekday() == 6

def print_subscriptions(
    printer,
    subscriptions_text,
):
    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, "SUBSCRIPTIONS")
    printer.set(bold=False)
    print_line(printer, "-")
    items = [
        printer_safe_text(
            line.strip()
        )
        for line in (
            subscriptions_text or ""
        ).splitlines()
        if line.strip()
    ]
    if not items:
        left(
            printer,
            "NO SUBSCRIPTIONS LISTED",
        )
        return
    for item in items:
        print_wrapped(
            printer,
            f"[ ] {item}",
            width=40,
        )
    print_line(printer, "-")

def print_footer(printer):
    print_line(printer, "=")

    printer_text(printer, "\n\n\n")


# ============================================================
# MAIN
# ============================================================

def _print_section_error(
    printer,
    heading,
    message="DATA UNAVAILABLE",
):
    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, heading)
    printer.set(bold=False)
    left(printer, message)


def run_live_pipeline():

    print(
        "Connecting to thermal printer..."
    )

    # ==========================================
    # CONTROL SETTINGS
    # ==========================================

    settings = (
        load_receipt_settings()
    )

    clear_route_cache()

    printer = Usb(
        PRINTER_VENDOR_ID,
        PRINTER_PRODUCT_ID,
    )

    printer.profile.profile_data[
        "media"
    ]["width"]["pixels"] = 576

    setup_printer(printer)
    print_header(printer)

    # ==========================================
    # WEATHER
    # ==========================================

    if feature_enabled(
        settings,
        "weather",
    ):
        try:
            print(
                "Downloading Stirchley weather..."
            )

            weather = get_weather()

            print_weather(
                printer,
                weather,
            )

        except Exception as error:
            print(
                "Weather error:",
                repr(error),
            )

            _print_section_error(
                printer,
                "WEATHER ERROR",
            )

    # ==========================================
    # NATIONAL NEWS
    # ==========================================

    if feature_enabled(
        settings,
        "national_news",
    ):
        try:
            news_count = int(
                display_value(
                    settings,
                    "news_count",
                    NEWS_HEADLINES,
                )
            )

            print(
                "Downloading today's UK news..."
            )

            headlines = (
                get_top_news_headlines(
                    news_count
                )
            )

            print_news(
                printer,
                headlines,
            )

        except Exception as error:
            print(
                "UK news error:",
                repr(error),
            )

    # ==========================================
    # BIRMINGHAM NEWS
    # ==========================================

    if feature_enabled(
        settings,
        "local_news",
    ):
        try:
            news_count = int(
                display_value(
                    settings,
                    "news_count",
                    LOCAL_NEWS_HEADLINES,
                )
            )

            print(
                "Downloading today's "
                "Birmingham news..."
            )

            local_headlines = (
                get_birmingham_news_headlines(
                    news_count
                )
            )

            print_local_news(
                printer,
                local_headlines,
            )

        except Exception as error:
            print(
                "Birmingham news error:",
                repr(error),
            )

    # ==========================================
    # CUT RECEIPT
    # ==========================================

    cut_receipt_section(
        printer
    )

    # ==========================================
    # VEHICLE CHECK
    # ==========================================

    print(
        "Checking vehicle MOT/tax..."
    )

    print_vehicle_expiry_checks(
        printer,
        vehicles,
        dvla_api_key,
    )

    # ==========================================
    # VILLA
    # ==========================================

    if feature_enabled(
            settings,
            "villa",
    ):
        try:
            villa_match = (
                get_aston_villa_match_today(
                    FOOTBALL_DATA_API_KEY
                )
            )

            if villa_match:
                print_villa_matchday(
                    printer,
                    villa_match,

                    include_trains=(
                        feature_enabled(
                            settings,
                            "villa_trains",
                        )
                    ),

                    transport_app_id=(
                        TRANSPORT_API_APP_ID
                    ),

                    transport_app_key=(
                        TRANSPORT_API_APP_KEY
                    ),

                    left=left,
                    centre=centre,
                    line=print_line,
                    safe_text=printer_safe_text,
                )

        except Exception as error:
            print(
                "Villa match-day error:",
                repr(error),
            )

    # ==========================================
    # CALENDAR
    # ==========================================

    events = []
    upcoming_events = []

    if feature_enabled(
        settings,
        "calendar",
    ):
        try:
            print(
                "Downloading Google Calendar..."
            )

            events = get_calendar_events(
                CALENDAR_ICAL_URL,
                days_ahead=0,
            )

            upcoming_events = (
                get_calendar_events(
                    CALENDAR_ICAL_URL,
                    days_ahead=3,
                )
            )

            print_calendar(
                printer,
                events,
            )

        except Exception as error:
            print(
                "Calendar error:",
                repr(error),
            )

            _print_section_error(
                printer,
                "CALENDAR ERROR",
            )

    # ==========================================
    # GOOGLE DOC / TO-DO
    # ==========================================

    document_1 = ""

    try:
        print(
            "Downloading Google Doc #1..."
        )

        document_1 = (
            get_google_doc_text(
                GOOGLE_DOC_1_URL
            )
        )

        print_google_doc(
            printer,
            document_1,
            upcoming_events,
        )

    except Exception as error:
        print(
            "Document 1 error:",
            repr(error),
        )

        traceback.print_exc()

    # ==========================================
    # TRIGGERS
    # ==========================================

    doc_finance = (
        finance_requested(
            document_1
        )
    )

    doc_food_shop = (
        food_shop_requested(
            document_1
        )
    )

    doc_shopping_list = (
        shopping_list_requested(
            document_1
        )
    )

    web_finance = (
        one_shot_requested(
            settings,
            "finance_check",
        )
    )

    web_food_shop = (
        one_shot_requested(
            settings,
            "food_shop",
        )
    )

    web_shopping_list = (
        one_shot_requested(
            settings,
            "shopping_list",
        )
    )

    today = datetime.now(
        ZoneInfo("Europe/London")
    ).date()

    # Keep scheduled finance independent
    # of Google Doc punctuation.
    scheduled_finance = (
        today.weekday() == 6
    )

    should_run_finance = (
        scheduled_finance
        or doc_finance
        or web_finance
    )

    should_run_food_shop = (
        doc_food_shop
        or web_food_shop
    )

    should_run_shopping_list = (
        doc_shopping_list
        or web_shopping_list
    )

    # ==========================================
    # FOOD SHOP
    # ==========================================

    if should_run_food_shop:

        food_shop_success = False

        try:
            print(
                "Food shop requested..."
            )

            food_shop_text = (
                get_google_doc_text(
                    FOOD_SHOP_GOOGLE_DOC_URL
                )
            )

            print_food_shop_check(
                printer,
                food_shop_text,
            )

            food_shop_success = True

        except Exception as error:
            print(
                "Food shop error:",
                repr(error),
            )

            traceback.print_exc()

            _print_section_error(
                printer,
                "FOOD SHOP ERROR",
                "ITEM LIST UNAVAILABLE",
            )

        if (
                food_shop_success
                and web_food_shop
        ):
            consume_one_shot(
                settings,
                "food_shop",
            )

    # ==========================================
    # SHOPPING LIST
    # ==========================================

    if should_run_shopping_list:

        shopping_list_success = False

        try:
            print(
                "Shopping list requested..."
            )

            shopping_list_success = True

        except Exception as error:
            print(
                "Shopping list error:",
                repr(error),
            )

            traceback.print_exc()

            _print_section_error(
                printer,
                "SHOPPING LIST ERROR",
                "SHOPPING LIST UNAVAILABLE",
            )

        if (
            shopping_list_success
            and web_shopping_list
        ):
            consume_one_shot(
                settings,
                "shopping_list",
            )

    # ==========================================
    # SUNDAY SUBSCRIPTIONS
    # ==========================================

    if should_print_subscriptions():

        try:
            subscriptions_text = (
                get_google_doc_text(
                    SUBSCRIPTIONS_GOOGLE_DOC_URL
                )
            )

            print_subscriptions(
                printer,
                subscriptions_text,
            )

        except Exception as error:
            print(
                "Subscriptions error:",
                repr(error),
            )

    # ==========================================
    # DELIVERIES
    # ==========================================

    if feature_enabled(
        settings,
        "deliveries",
    ):
        try:
            print(
                "Checking upcoming deliveries..."
            )

            deliveries = (
                get_upcoming_deliveries()
            )

            print_upcoming_deliveries(
                printer,
                deliveries,
            )

        except Exception as error:
            print(
                "Delivery error:",
                repr(error),
            )

    # ==========================================
    # EXERCISES
    # ==========================================

    try:
        document_2 = (
            get_google_doc_text(
                GOOGLE_DOC_2_URL
            )
        )

        print_random_document_lines(
            printer,
            document_2,
        )

    except Exception as error:
        print(
            "Document 2 error:",
            repr(error),
        )

    # ==========================================
    # CUT DAILY ACTIONS
    # ==========================================

    cut_receipt_section(
        printer
    )

    # ==========================================
    # MEAL PLANNER
    # ==========================================

    try:
        if today.weekday() == 5:

            meals.generate_week(
                meals.sunday_for(today),
            )

            meals.print_weekly_overview(
                printer,
                left,
                print_line,
            )

            meals.print_shopping_list(
                printer,
                left,
                print_line,
            )

        if today.weekday() == 6:

            meals.print_sunday_prep(
                printer,
                left,
                print_line,
            )

        meals.print_today_recipe(
            printer,
            left,
            print_line,
        )

    except Exception as error:
        print(
            "Meal planner error:",
            repr(error),
        )

        traceback.print_exc()

    print_footer(
        printer
    )

    printer.cut()

    # ==========================================
    # FINANCE - SEPARATE RECEIPT
    # ==========================================

    if should_run_finance:

        finance_success = False

        try:
            print(
                "Finance check requested..."
            )

            subscription_changes = []

            balances = (
                get_account_balances()
            )

            finance_data = (
                get_regular_finance_data()
            )

            if (
                isinstance(
                    finance_data,
                    tuple,
                )
                and len(finance_data) >= 5
            ):
                (
                    transactions,
                    direct_debits,
                    standing_orders,
                    subscriptions,
                    spending_summary,
                ) = finance_data[:5]

                subscription_changes = (
                    update_subscriptions_from_transactions(
                        transactions
                    )
                )

            else:
                transactions = []
                direct_debits = []
                standing_orders = []
                subscriptions = []
                spending_summary = {}

            print_integrated_finance(
                printer,
                left,
                print_line,
                balances=balances,
                transactions=transactions,
                direct_debits=direct_debits,
                standing_orders=standing_orders,
                subscriptions=subscriptions,
                spending_summary=spending_summary,
            )

            print_subscription_changes(
                printer,
                subscription_changes,
            )

            # Reload after transaction matching because
            # subscriptions.json may just have been updated.
            subscriptions_data = (
                load_subscriptions()
            )

            # Reload after transaction matching because
            # subscriptions.json may just have been updated.
            subscriptions_data = (
                load_subscriptions()
            )

            print_subscription_status(
                printer,
                left,
                print_line,
                transactions,
            )

            print_instalment_status(
                printer,
                subscriptions_data,
            )

            finance_success = True

        except Exception as error:
            print(
                "Finance check error:",
                repr(error),
            )

            traceback.print_exc()

            _print_section_error(
                printer,
                "FINANCE ERROR",
                "FINANCE DATA UNAVAILABLE",
            )

        if (
            finance_success
            and web_finance
        ):
            consume_one_shot(
                settings,
                "finance_check",
            )

        print_footer(
            printer
        )

        printer.cut()

    print(
        "Receipt printed successfully."
    )