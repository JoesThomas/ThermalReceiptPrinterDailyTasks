"""Bounded Gmail delivery collection and pure message parsing."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo
import email
import email.header
import imaplib
import re
from email.utils import parsedate_to_datetime
from services.observability import event


@dataclass(frozen=True)
class GmailConfig:
    address: str
    password: str = field(repr=False)
    host: str = "imap.gmail.com"
    search_days: int = 14
    max_messages: int = 100


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
        disposition = str(part.get("Content-Disposition", "")).lower()

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
            html_parts.append(_html_to_plain_text(text))

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


def collect(config):
    failed = False
    if not config.address or not config.password:
        print("Gmail IMAP credentials not configured; using delivery JSON fallback.")
        return [], failed

    import time as fetch_clock

    deadline = fetch_clock.monotonic() + 20
    mailbox = None

    try:
        mailbox = imaplib.IMAP4_SSL(config.host, timeout=5)

        from services.api_health import record as health_record

        mailbox.login(
            config.address,
            config.password,
        )

        status, _ = mailbox.select(
            "INBOX",
            readonly=True,
        )

        if status != "OK":
            health_record("Gmail", "failed", reason="unavailable")
            failed = True
            print("Could not open Gmail inbox.")
            return [], failed

        health_record("Gmail", "healthy")
        since_date = datetime.now(ZoneInfo("Europe/London")).date() - timedelta(
            days=config.search_days
        )

        status, data = mailbox.search(
            None,
            "SINCE",
            since_date.strftime("%d-%b-%Y"),
        )

        if status != "OK" or not data:
            failed = True
            health_record("Gmail", "failed", reason="unavailable")
            return [], failed

        message_ids = data[0].split()
        message_ids = message_ids[-config.max_messages :][::-1]

        records = []

        for message_id in message_ids:
            remaining = deadline - fetch_clock.monotonic()
            if remaining <= 0:
                failed = True
                break
            if getattr(mailbox, "sock", None) is not None:
                mailbox.sock.settimeout(min(5, remaining))
            status, message_data = mailbox.fetch(
                message_id,
                "(BODY.PEEK[]<0.524288>)",
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
                parsed_message = email.message_from_bytes(raw_message)
            except Exception:
                continue

            subject = _decode_email_header(parsed_message.get("Subject", ""))

            body = _extract_imap_message_body(parsed_message)

            is_delivery = _likely_delivery_email(
                subject,
                body,
            )

            if not is_delivery:
                continue

            try:
                received = parsedate_to_datetime(parsed_message.get("Date", ""))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=ZoneInfo("Europe/London"))
                received_date = (
                    received.astimezone(ZoneInfo("Europe/London")).date().isoformat()
                )
            except (TypeError, ValueError, OverflowError):
                received_date = None
            records.append(
                {
                    "email_subject": subject,
                    "email_body": body,
                    "email_received_at": received_date,
                }
            )

        return records, failed

    except imaplib.IMAP4.error as error:
        failed = True
        from services.api_health import record as health_record

        health_record("Gmail", "failed", reason="unavailable")
        event("gmail_delivery", status="failed", error=error)
        return [], failed

    except OSError as error:
        failed = True
        from services.api_health import record as health_record

        health_record("Gmail", "failed", reason="connection")
        event("gmail_delivery", status="failed", error=error)
        return [], failed

    finally:
        if mailbox is not None:
            try:
                if getattr(mailbox, "sock", None) is not None:
                    mailbox.sock.settimeout(1)
                mailbox.logout()
            except Exception:
                pass
