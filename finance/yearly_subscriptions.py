import json
import math
from zoneinfo import ZoneInfo
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path


DEFAULT_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "subscriptions.json"
)


def load_yearly_subscriptions(path=DEFAULT_FILE):
    path = Path(path)

    if not path.exists():
        return []

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []

    subscriptions = data.get("yearly", data.get("subscriptions", []))

    if not isinstance(subscriptions, list):
        return []

    return subscriptions


def _parse_date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo('Europe/London'))
        return parsed.date()
    except (TypeError, ValueError):
        return None


def next_renewal(subscription, today=None):
    today = today or date.today()

    original = _parse_date(
        subscription.get("renewal_date")
    )

    if not original:
        return None

    year = max(today.year, original.year)

    while True:
        # Handles 29 February subscriptions safely.
        day = min(
            original.day,
            monthrange(year, original.month)[1],
        )

        candidate = date(
            year,
            original.month,
            day,
        )

        if candidate >= today:
            return candidate

        year += 1


def upcoming_yearly_subscriptions(
    subscriptions,
    today=None,
    days=30,
):
    today = today or date.today()
    upcoming = []

    for subscription in subscriptions:
        renewal = next_renewal(
            subscription,
            today,
        )

        if not renewal:
            continue

        days_until = (renewal - today).days

        if 0 <= days_until <= days:
            item = dict(subscription)
            item["next_renewal"] = renewal
            item["days_until"] = days_until
            upcoming.append(item)

    return sorted(
        upcoming,
        key=lambda item: item["next_renewal"],
    )


def yearly_subscription_summary(
    subscriptions,
):
    total = sum(
        float(item.get("amount", 0) or 0)
        for item in subscriptions
    )

    categories = {}

    for item in subscriptions:
        category = (
            item.get("category")
            or "Other"
        )

        categories[category] = (
            categories.get(category, 0.0)
            + float(item.get("amount", 0) or 0)
        )

    return {
        "annual_total": round(total, 2),
        "monthly_equivalent": round(
            total / 12,
            2,
        ),
        "categories": categories,
    }

def annual_subscription_rows(subscriptions, transactions, today):
    """Show annual renewals without treating an absent bank match as unpaid."""
    rows = []
    for subscription in subscriptions or []:
        anchor = _parse_date(subscription.get("renewal_date"))
        renewal = next_renewal(subscription, today)
        last_paid = _parse_date(subscription.get("last_paid"))
        match_terms = subscription.get("match") or []
        if isinstance(match_terms, str):
            match_terms = [match_terms]
        terms = [str(term).casefold().strip() for term in match_terms if str(term).strip()]
        try:
            expected = float(subscription.get("amount"))
        except (ValueError, TypeError):
            expected = None

        # A monthly payment to the same merchant must not verify the annual bill.
        cycle = None
        if anchor and anchor.year <= today.year:
            cycle = date(today.year, anchor.month,
                         min(anchor.day, monthrange(today.year, anchor.month)[1]))
        matches = []
        if cycle and expected is not None and math.isfinite(expected) and expected > 0 and terms:
            for tx in transactions or []:
                paid_on = _parse_date(tx.get("timestamp") or tx.get("transaction_date")
                                      or tx.get("date"))
                if not paid_on or paid_on > today or abs((paid_on - cycle).days) > 30:
                    continue
                if str(tx.get("transaction_type", "")).upper() in {"CREDIT", "REFUND"}:
                    continue
                try:
                    amount = float(tx.get("amount"))
                except (ValueError, TypeError):
                    continue
                if not math.isfinite(amount) or amount >= 0 or abs(abs(amount) - expected) > 0.01:
                    continue
                description = " ".join(str(tx.get(key) or "") for key in
                                       ("merchant_name", "description")).casefold()
                if any(term in description for term in terms):
                    matches.append(paid_on)

        rows.append({**subscription, "next_renewal": renewal,
                     "last_paid_date": last_paid, "bank_paid_date": max(matches) if matches else None,
                     "days_until": (renewal - today).days if renewal else None})
    return sorted(rows, key=lambda row: (row["next_renewal"] or date.max,
                                          str(row.get("name", "")).casefold()))
