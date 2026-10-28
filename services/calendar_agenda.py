"""Combine personal events with Villa fixtures, preserving existing calendar entries."""

from datetime import date
import re
from services.villa_fixtures import UK


def words(value):
    return re.findall(r"[a-z0-9]+", str(value).casefold())


def same_fixture(event, match):
    if event.get("fixture_id") == match["id"]:
        return True
    try:
        on = event.get("date")
        on = on if isinstance(on, date) else date.fromisoformat(str(on))
    except (TypeError, ValueError):
        return False
    if on != match["kickoff"].astimezone(UK).date():
        return False
    title = words(event.get("title", ""))
    tokens = set(title)
    if not tokens & {"villa", "avfc", "villans"}:
        return False
    if tokens & {
        "women",
        "womens",
        "ladies",
        "u21",
        "u18",
        "train",
        "trains",
        "travel",
        "parking",
        "tickets",
    }:
        return False
    opponent = match["away_team"] if match["is_home"] else match["home_team"]
    meaningful = set(words(opponent)) - {"afc", "fc", "football", "club", "f", "c"}
    code = match.get("away_code" if match["is_home"] else "home_code", "").casefold()
    if meaningful and meaningful <= tokens or code and code in tokens:
        return True
    # A generic, unambiguous Villa-match label also represents the fixture.
    return tokens <= {
        "aston",
        "villa",
        "avfc",
        "villans",
        "match",
        "game",
        "football",
        "home",
        "away",
        "fc",
        "watch",
        "watching",
    }


def fixture_event(match):
    kickoff = match["kickoff"].astimezone(UK)
    opponent = match["away_team"] if match["is_home"] else match["home_team"]
    return dict(
        uid="villa-fixture:" + match["id"],
        fixture_id=match["id"],
        date=kickoff.date(),
        time=kickoff.strftime("%H:%M"),
        title="Aston Villa v "
        + opponent
        + (" (home)" if match["is_home"] else " (away)"),
        location=match.get("venue", ""),
        competition=match.get("competition", ""),
        start_dt=kickoff,
        end_dt=kickoff,
        all_day=False,
        source="villa_fixture",
    )


def merge(events, fixtures):
    rows = [dict(row) for row in events]
    for match in fixtures:
        if not any(same_fixture(row, match) for row in rows):
            rows.append(fixture_event(match))
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("date", "")),
            str(row.get("time", "")),
            row.get("title", ""),
        ),
    )


def collect(ical_url, today, days, *, include_villa=True, api_key=""):
    from services.source_cache import get
    from services.calendar_source import collect as personal
    from services.villa_fixtures import matches
    from receipt.freshness import mark, snapshot
    from services.calendar_locations import apply

    events, fixtures, warnings = [], [], []
    try:
        if not ical_url:
            raise ValueError("Personal calendar not configured")
        events = get(
            "Calendar",
            f"{ical_url}|{today}|{days}",
            lambda: personal(ical_url, today, days),
        )
    except Exception:
        mark("Calendar", "unavailable")
        warnings.append("Personal calendar unavailable; check your iCal connection.")
    if include_villa:
        try:
            fixtures = matches(api_key, today=today, days=days)
            status = snapshot().get("Villa fixtures", {}).get("status", "")
            if status == "partial":
                warnings.append(
                    "Villa fixture coverage may be incomplete; check the club schedule."
                )
            elif status in {
                "cached after error",
                "cached after partial result",
                "cached during retry delay",
            }:
                warnings.append(
                    "Villa fixtures use cached data; confirm kick-off changes."
                )
        except Exception:
            warnings.append("Villa fixtures unavailable; check the club schedule.")
    checks = snapshot()
    sources = [checks.get("Calendar", {})] + (
        [checks.get("Villa fixtures", {})] if include_villa else []
    )
    stamps = [row.get("source_checked_at") or row.get("checked_at") for row in sources]
    stamps = [stamp for stamp in stamps if stamp]
    cached = any(str(row.get("status", "")).startswith("cached") for row in sources)
    mark(
        "Calendar agenda",
        "partial" if warnings else "cached" if cached else "checked",
        source_checked_at=min(stamps) if stamps else None,
        warnings=warnings,
    )
    return apply(merge(events, fixtures))
