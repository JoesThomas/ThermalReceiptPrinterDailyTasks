import json
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

from finance.bill_payments import exact_amount, payment_candidates, posted_date as _parse_date
from finance.money import PENNY, parse


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
    used = set()
    for index, subscription in enumerate(subscriptions or []):
        anchor = _parse_date(subscription.get("renewal_date"))
        renewal = next_renewal(subscription, today)
        last_paid = _parse_date(subscription.get("last_paid"))
        expected = parse(subscription.get("amount"))
        match = None
        cycle = None
        if anchor and anchor.year <= today.year and expected is not None and expected > 0:
            cycle = date(today.year, anchor.month,
                         min(anchor.day, monthrange(today.year, anchor.month)[1]))
            start = cycle - timedelta(days=30)
            candidates = [
                candidate for candidate in payment_candidates(
                    subscription, transactions or [], today,
                    start=max(start, last_paid or start), end=cycle + timedelta(days=30)
                ) if candidate[0] not in used
            ]
            exact = exact_amount(candidates, expected)
            if exact:
                match = min(exact, key=lambda candidate: abs((candidate[1] - cycle).days))
            else:
                # Allow a higher renewal only close to its expected date. A
                # cheaper monthly charge must not verify an annual renewal.
                close = [candidate for candidate in candidates if abs((candidate[1] - cycle).days) <= 7]
                if len(close) == 1:
                    amount = close[0][2]
                    previously_paid = any(parse(entry.get("amount")) == amount
                                          for entry in subscription.get("history", [])
                                          if isinstance(entry, dict))
                    if amount > expected + PENNY or previously_paid:
                        match = close[0]

        if match:
            used.add(match[0])
        rows.append({**subscription, "subscription_index": index, "next_renewal": renewal,
                     "bank_match_index": match[0] if match else None,
                     "last_paid_date": last_paid, "bank_paid_date": match[1] if match else None,
                     "bank_paid_amount": float(match[2]) if match else None,
                     "matched_renewal": cycle if match else None,
                     "days_until": (renewal - today).days if renewal else None})
    return sorted(rows, key=lambda row: (row["next_renewal"] or date.max,
                                          str(row.get("name", "")).casefold()))
