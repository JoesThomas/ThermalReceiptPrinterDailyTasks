"""Bounded public club fixtures, including cup ties; no calendar/account writes."""

from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import re
import time
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
URL = "https://next.avfc.co.uk/matches"


class FixtureData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if (
            tag == "script"
            and attrs.get("type") == "application/json"
            and "data-nuxt-data" in attrs
        ):
            self.active = True
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.documents.append("".join(self.parts))
            self.active = False


def parse_club_page(content):
    """Read only known fields from Nuxt's indexed JSON, never execute scripts."""
    if len(content) > 2_000_000:
        raise ValueError("Villa fixture response exceeds size limit")
    parser = FixtureData()
    parser.feed(content)
    results = {}
    recognized = False
    for document in parser.documents:
        pool = json.loads(document)
        if not isinstance(pool, list) or len(pool) > 50000:
            continue

        def ref(value):
            return (
                pool[value] if type(value) is int and 0 <= value < len(pool) else None
            )

        def field(row, key):
            return ref(row.get(key)) if isinstance(row, dict) else None

        for row in pool:
            if (
                not isinstance(row, dict)
                or "kickOffUTC" not in row
                or "teamData" not in row
            ):
                continue
            recognized = True
            if field(row, "slugTeamName") != "mens":
                continue
            status = str(field(row, "matchStatus") or "").casefold()
            if status in {"cancelled", "canceled", "postponed", "abandoned"}:
                continue
            stamp = field(row, "kickOffUTC")
            try:
                kickoff = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if kickoff.tzinfo is None:
                    continue
                kickoff = kickoff.astimezone(UK)
            except (AttributeError, ValueError, TypeError):
                continue
            team_refs = field(row, "teamData")
            if not isinstance(team_refs, list) or len(team_refs) != 2:
                continue
            teams = {}
            for index in team_refs:
                team = ref(index)
                side = field(team, "side")
                name = field(team, "teamName")
                if side in {"Home", "Away"} and isinstance(name, str) and name.strip():
                    teams[side] = (
                        name.strip()[:120],
                        str(field(team, "teamNameInitials") or "")[:8],
                    )
            if set(teams) != {"Home", "Away"} or not any(
                is_villa(t[0]) for t in teams.values()
            ):
                continue
            identifier = field(row, "id")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,80}", identifier
            ):
                continue
            results[identifier] = dict(
                id=identifier,
                kickoff=kickoff,
                home_team=teams["Home"][0],
                away_team=teams["Away"][0],
                home_code=teams["Home"][1],
                away_code=teams["Away"][1],
                competition=str(field(row, "competitionName") or "")[:120],
                venue=str(field(row, "venue") or "")[:200],
                is_home=is_villa(teams["Home"][0]),
                source="Aston Villa official fixtures",
            )
    if not recognized or not results:
        raise ValueError("Villa fixture format unavailable; check official schedule")
    return sorted(results.values(), key=lambda row: row["kickoff"])


def is_villa(name):
    return re.sub(r"[^a-z]", "", name.casefold()) in {
        "astonvilla",
        "astonvillafc",
        "avfc",
    }


def collect_club():
    from services.api_health import observed_request

    deadline = time.monotonic() + 15
    response = observed_request("Football API", "get", URL, timeout=(5, 8), stream=True)
    try:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000 or time.monotonic() > deadline:
                raise ValueError("Villa fixture download exceeds size limit")
            chunks.append(chunk)
        return parse_club_page(b"".join(chunks).decode("utf-8-sig"))
    finally:
        response.close()


def collect_api(api_key, today, days):
    from http_client import get
    from services.api_health import observed_call

    response = observed_call(
        "Football API",
        get,
        "https://api.football-data.org/v4/teams/58/matches",
        headers={"X-Auth-Token": api_key},
        params={
            "dateFrom": str(today - timedelta(days=1)),
            "dateTo": str(today + timedelta(days=days)),
        },
        timeout=10,
    )
    response.raise_for_status()
    result = []
    for row in response.json().get("matches", []):
        home, away = row.get("homeTeam") or {}, row.get("awayTeam") or {}
        if not (home.get("id") == 58 or away.get("id") == 58):
            continue
        if row.get("status") in {"CANCELLED", "POSTPONED", "SUSPENDED"}:
            continue
        try:
            kickoff = datetime.fromisoformat(row["utcDate"].replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                continue
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        result.append(
            dict(
                id="api-" + str(row["id"]),
                kickoff=kickoff.astimezone(UK),
                home_team=str(home.get("name") or ""),
                away_team=str(away.get("name") or ""),
                home_code=str(home.get("tla") or ""),
                away_code=str(away.get("tla") or ""),
                competition=str((row.get("competition") or {}).get("name") or ""),
                venue="",
                is_home=home.get("id") == 58,
                source="Football API (coverage may be limited)",
            )
        )
    return result


def matches(api_key="", *, today=None, days=0):
    from receipt.local_time import uk_today
    from services.source_cache import get
    from receipt.freshness import mark

    today = today or uk_today()
    if type(days) is not int or not 0 <= days <= 31:
        raise ValueError("Villa fixture range must be 0–31 days")

    try:
        rows = get("Villa fixtures", URL + "|v1", collect_club, ttl=900, max_age=21600)
    except Exception:
        if not api_key:
            raise
        rows = get(
            "Villa fixture fallback",
            str(today),
            lambda: collect_api(api_key, today, 31),
            ttl=900,
            max_age=21600,
        )
        mark("Villa fixtures", "partial")
    end = today + timedelta(days=days)
    return [
        row
        for row in rows
        if isinstance(row.get("kickoff"), datetime)
        and today <= row["kickoff"].astimezone(UK).date() <= end
    ]
