"""Small read-only attention model; no provider requests or transaction reads."""

from datetime import datetime, timezone
from pathlib import Path
from receipt.local_time import UK
from storage import PrivateStore
from services.retry_policy import pending, retry_epoch
from web_control.schedule_history import summary


def read(path):
    try:
        value = PrivateStore(path, default=dict, max_bytes=100000).read()
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def build(root, settings, *, warning=None, daily=None, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    items = []

    def add(key, title, detail, endpoint, label, **params):
        items.append(
            dict(
                id=key,
                title=title,
                detail=detail,
                endpoint=endpoint,
                label=label,
                params=params,
            )
        )

    if warning:
        add(
            "settings",
            "Settings need review",
            "Recovered settings are in use; automatic printing is paused.",
            "index",
            "Review settings",
            view="settings",
        )
    daily = daily or summary(settings, now=now, directory=root / "data")
    if daily["today"]["state"] in {
        "failed",
        "timed_out",
        "cancelled",
        "interrupted",
        "missed",
        "unavailable",
    }:
        add(
            "daily-print",
            "Daily receipt needs review",
            daily["today"]["label"],
            "archive_list",
            "Review saved receipts",
            date=now.astimezone(UK).date().isoformat(),
        )
    job = read(root / "data" / "web_print_status.json")
    if job.get("state") in {"failed", "timed_out", "cancelled"} and not any(
        i["id"] == "daily-print" for i in items
    ):
        add(
            "print",
            "Latest print did not complete",
            "Review its saved preview before requesting another print.",
            "preview",
            "Review preview",
        )
    printer = read(root / "data" / "printer_diagnostics.json")
    sensors = printer.get("sensors") or {}
    if not isinstance(sensors, dict):
        sensors = {}
    if (
        printer.get("reachable") is False
        or sensors.get("paper") == "out"
        or sensors.get("cover") == "open"
        or sensors.get("error") == "reported"
    ):
        add(
            "printer",
            "Printer needs checking",
            "The last diagnostic reported an issue. Recheck after refilling paper or closing the cover.",
            "printer_diagnostics",
            "Check printer / test paper",
        )
    bank = read(root / "cache" / "finance_review" / "status.json")
    failed = bank.get("state") == "failed"
    try:
        started = datetime.fromisoformat(bank["started_at"])
        failed = (
            failed
            or bank.get("state") == "running"
            and (now - started).total_seconds() > 630
        )
    except (KeyError, ValueError, TypeError):
        pass
    if failed:
        add(
            "bank",
            "Bank refresh needs attention",
            "The last refresh failed or stopped. Previous data may be shown; forecasts can be withheld.",
            "finance_review",
            "Review bank data",
        )
    elif bank.get("state") == "completed" and bank.get("coverage") == "partial":
        add(
            "bank-partial",
            "Some bank data is unavailable",
            "The last bank refresh was partial; check missing sources before relying on forecasts.",
            "finance_review",
            "Review bank sources",
        )
    elif bank.get("state") == "completed":
        try:
            checked = datetime.fromisoformat(bank["checked_at"])
            stale = (now - checked).total_seconds() > 1800 or checked.astimezone(
                UK
            ).date() != now.astimezone(UK).date()
        except (KeyError, ValueError, TypeError):
            stale = True
        if stale:
            add(
                "bank-stale",
                "Bank data needs refreshing",
                "The saved bank check is beyond its freshness window.",
                "finance_review",
                "Refresh bank data",
            )
    health = read(root / "data" / "api_health.json").get("services", {})
    if isinstance(health, dict):
        from services.api_health import PUBLIC, OBSERVED

        allowed = set(
            (
                *PUBLIC,
                *OBSERVED,
                "Google Calendar",
                "Google Docs – tasks",
                "Google Docs – exercises",
                "Google Docs – food shop",
                "Google Docs – subscriptions",
            )
        )
        affected = [
            name
            for name, row in health.items()
            if name in allowed
            and isinstance(row, dict)
            and (
                row.get("status") == "failed"
                or pending(row.get("next_retry_at"), now.timestamp())
            )
        ]
    else:
        affected = []
    cache = read(root / "data" / "source_retry_status.json").get("services")
    if not isinstance(cache, dict):
        cache = read(root / "data" / "source_cache.json")
    delayed = {
        row.get("name")
        for row in cache.values()
        if isinstance(row, dict)
        and isinstance(row.get("name"), str)
        and retry_epoch(row.get("next_retry_epoch")) > now.timestamp()
    }
    if affected or delayed:
        names = sorted(
            set(affected)
            | {
                name
                for name in delayed
                if name
                in {
                    "Weather",
                    "UK news",
                    "Local news",
                    "Sport news",
                    "Calendar",
                    "Deliveries",
                }
            }
        )
        add(
            "integrations",
            "Some integrations need attention",
            ", ".join(names[:8])
            + ". Automatic retries may be delayed; a manual retry is available.",
            "api_health_page",
            "Review integrations",
        )
    return items
