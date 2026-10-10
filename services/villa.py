from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
)

from zoneinfo import ZoneInfo

from http_client import get


ASTON_VILLA_TEAM_ID = 58

BOURNVILLE_CRS = "BRV"
ASTON_CRS = "AST"

MATCH_TRAIN_WINDOW_HOURS = 2


def get_aston_villa_match_today(
    football_api_key,
):
    if not football_api_key:
        return None

    london = ZoneInfo(
        "Europe/London"
    )

    today = datetime.now(
        london
    ).date()

    from services.api_health import observed_call
    response = observed_call("Football API", get,
        (
            "https://api.football-data.org/"
            f"v4/teams/{ASTON_VILLA_TEAM_ID}/"
            "matches"
        ),
        headers={
            "X-Auth-Token":
                football_api_key,
        },
        params={
            "dateFrom":
                today.isoformat(),

            "dateTo":
                today.isoformat(),
        },
        timeout=15,
    )

    response.raise_for_status()

    for match in (
        response.json()
        .get("matches", [])
    ):

        utc_date = match.get(
            "utcDate"
        )

        if not utc_date:
            continue

        try:
            kickoff = (
                datetime
                .fromisoformat(
                    str(
                        utc_date
                    ).replace(
                        "Z",
                        "+00:00",
                    )
                )
                .astimezone(
                    london
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if kickoff.date() != today:
            continue

        home = (
            match.get("homeTeam")
            or {}
        )

        away = (
            match.get("awayTeam")
            or {}
        )

        competition = (
            match.get("competition")
            or {}
        )

        return {
            "kickoff": kickoff,

            "home_team":
                home.get(
                    "name",
                    "",
                ),

            "away_team":
                away.get(
                    "name",
                    "",
                ),

            "competition":
                competition.get(
                    "name",
                    "",
                ),

            "is_home": (
                home.get("id")
                == ASTON_VILLA_TEAM_ID
            ),
        }

    return None


def _rail_time(
    date_value,
    time_text,
):
    if not time_text:
        return None

    try:
        parsed = datetime.strptime(
            time_text,
            "%H:%M",
        ).time()

    except ValueError:
        return None

    return datetime.combine(
        date_value,
        parsed,
        tzinfo=ZoneInfo(
            "Europe/London"
        ),
    )


def get_villa_matchday_trains(
    kickoff,
    transport_app_id,
    transport_app_key,
):
    if not transport_app_id:
        raise RuntimeError(
            "TransportAPI app ID "
            "not configured."
        )

    if not transport_app_key:
        raise RuntimeError(
            "TransportAPI app key "
            "not configured."
        )

    window_start = (
        kickoff
        - timedelta(
            hours=
                MATCH_TRAIN_WINDOW_HOURS
        )
    )

    url = (
        "https://transportapi.com/"
        "v3/uk/train/station/"
        f"{BOURNVILLE_CRS}/"
        f"{window_start:%Y-%m-%d}/"
        f"{window_start:%H:%M}/"
        "timetable.json"
    )

    response = get(
        url,
        params={
            "app_id":
                transport_app_id,

            "app_key":
                transport_app_key,

            "calling_at":
                ASTON_CRS,

            "train_status":
                "passenger",
        },
        timeout=20,
    )

    response.raise_for_status()

    services = (
        response.json()
        .get("departures", {})
        .get("all", [])
    )

    trains = []

    for service in services:

        departure = _rail_time(
            kickoff.date(),
            service.get(
                "aimed_departure_time"
            ),
        )

        if not departure:
            continue

        if not (
            window_start
            <= departure
            < kickoff
        ):
            continue

        expected = _rail_time(
            kickoff.date(),
            (
                service.get(
                    "expected_departure_time"
                )
            ),
        )

        trains.append({
            "departure":
                departure,

            "expected_departure":
                expected,

            "platform":
                service.get(
                    "platform"
                )
                or "-",

            "status":
                service.get(
                    "status"
                )
                or "",
            "arrival": None,
            "timetable_url": (service.get("service_timetable") or {}).get("id"),
            "train_uid": service.get("train_uid"),
        })

    trains.sort(
        key=lambda train:
            train["departure"]
    )

    # Optional arrival enrichment must not prevent departure times being shown.
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlsplit, urlunsplit

    def arrival(train):
        reason = "no timetable reference"
        try:
            url = urlsplit(train.get("timetable_url") or "")
            if not url.path and train.get("train_uid"):
                from urllib.parse import quote
                uid = quote(str(train["train_uid"]), safe="")
                url = urlsplit(f"https://transportapi.com/v3/uk/train/service/train_uid:{uid}/{kickoff:%Y-%m-%d}/timetable.json")
            if url.scheme not in {"http", "https"} or url.netloc != "transportapi.com" or not url.path.startswith("/v3/uk/train/service/"):
                train["arrival_reason"] = reason
                return
            # Some timetable references use HTTP; always upgrade to HTTPS.
            response = get(urlunsplit(("https", url.netloc, url.path, "", "")),
                           params={"app_id": transport_app_id, "app_key": transport_app_key}, timeout=5)
            code = response.status_code
            if isinstance(code, int) and code >= 400:
                reason = f"HTTP {code}"
            response.raise_for_status()
            stops = response.json().get("stops", [])
            reason = "Aston stop not returned"
            for stop in stops:
                code = str(stop.get("station_code") or "").upper()
                name = str(stop.get("station_name") or "").strip().casefold()
                if code == ASTON_CRS or name == "aston":
                    train["arrival"] = _rail_time(kickoff.date(), stop.get("aimed_arrival_time"))
                    reason = "arrival time missing" if train["arrival"] is None else "loaded"
                    break
        except Exception as error:
            if not reason.startswith("HTTP"):
                reason = type(error).__name__
        finally:
            train["arrival_reason"] = reason
            if train.get("arrival") is None:
                # Never print exception messages or API URLs containing keys.
                print(f"Villa arrival debug: departure={train['departure']:%H:%M} reason={reason}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(arrival, trains))
    return trains

def print_villa_matchday(
    printer,
    match,
    *,
    include_trains=False,
    transport_app_id="",
    transport_app_key="",
    left,
    centre,
    line,
    safe_text,
):
    """
    Print today's Aston Villa home match and, optionally,
    Bournville -> Aston trains before kick-off.
    """

    if not match:
        return

    # Only print the match-day section for Villa home games.
    if not match.get("is_home", False):
        return

    kickoff = match.get("kickoff")

    if not isinstance(kickoff, datetime):
        return

    # ==========================================
    # MATCH
    # ==========================================

    line(
        printer,
        "=",
    )

    printer.set(
        bold=True,
    )

    centre(
        printer,
        "MATCH DAY",
    )

    printer.set(
        bold=False,
    )

    line(
        printer,
        "-",
    )

    centre(
        printer,
        "ASTON VILLA",
    )

    centre(
        printer,
        "v",
    )

    opposition = safe_text(
        match.get(
            "away_team",
            "OPPOSITION",
        )
    ).upper()

    centre(
        printer,
        opposition,
    )

    competition = safe_text(
        match.get(
            "competition",
            "",
        )
    ).upper()

    if competition:
        printer.text("\n")

        centre(
            printer,
            competition,
        )

    printer.text("\n")

    left(
        printer,
        (
            f"{'KICK OFF':<32}"
            f"{kickoff.strftime('%H:%M'):>10}"
        ),
    )

    # ==========================================
    # TRAINS
    # ==========================================

    if include_trains:

        failed = False
        try:
            trains = get_villa_matchday_trains(
                kickoff,
                transport_app_id,
                transport_app_key,
            )

        except Exception as error:
            failed = True
            # HTTP error URLs can contain credentials; log only the error type.
            print("Villa train error:", type(error).__name__)

            trains = []

        if trains:

            line(
                printer,
                "-",
            )

            printer.set(
                bold=True,
            )

            left(
                printer,
                "TRAVEL",
            )

            printer.set(
                bold=False,
            )

            left(
                printer,
                "BOURNVILLE -> ASTON",
            )

            printer.text("\n")

            for train in trains:

                departure_dt = train.get(
                    "departure"
                )

                expected_dt = train.get(
                    "expected_departure"
                )

                if not departure_dt:
                    continue

                departure = (
                    departure_dt.strftime(
                        "%H:%M"
                    )
                )

                platform = train.get("platform")
                platform_text = f"Platform {safe_text(str(platform))}" if platform and platform != "-" else "Platform TBC"
                raw_status = str(train.get("status", "")).upper()
                if "CANCEL" in raw_status:
                    status = "CANCELLED"
                elif expected_dt and expected_dt != departure_dt:
                    status = "EXP " + expected_dt.strftime("%H:%M")
                elif expected_dt:
                    status = "ON TIME"
                else:
                    status = "SCHEDULED"
                left(printer, f"{departure:<7}{platform_text:<18}{status:>17}")
                arrival = train.get("arrival")
                left(printer, "  Aston arrival: " + (arrival.strftime("%H:%M") + " (scheduled)" if arrival else "unavailable"))
        else:
            line(printer, "-")
            left(printer, "TRAVEL: BOURNVILLE -> ASTON")
            left(printer, "Train times unavailable" if failed else "No trains returned before kick-off")

    line(
        printer,
        "=",
    )