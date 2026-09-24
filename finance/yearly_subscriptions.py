import json
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path


DEFAULT_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "yearly_subscriptions.json"
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

    subscriptions = data.get("subscriptions", [])

    if not isinstance(subscriptions, list):
        return []

    return subscriptions


def _parse_date(value):
    try:
        return datetime.strptime(
            str(value),
            "%Y-%m-%d",
        ).date()
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