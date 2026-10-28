"""Home/away cup fixtures reach the shared agenda without repeated match entries."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import json
from services import villa_fixtures as fixtures, calendar_agenda as agenda, villa
from receipt.freshness import reset, snapshot
from receipt.sections import print_calendar
from receipt.profile import COLUMNS

TODAY = date(2026, 10, 28)


def match(**changes):
    return dict(
        dict(
            id="cup-123",
            kickoff=datetime(2026, 10, 28, 19, 45, tzinfo=fixtures.UK),
            home_team="AFC Bournemouth",
            away_team="Aston Villa",
            home_code="BOU",
            away_code="AVL",
            competition="English League Cup",
            venue="Vitality Stadium",
            is_home=False,
        ),
        **changes,
    )


def club_page(*rows, **changes):
    pool = []

    def pack(value):
        index = len(pool)
        pool.append(None)
        if isinstance(value, dict):
            pool[index] = {k: pack(v) for k, v in value.items()}
        elif isinstance(value, list):
            pool[index] = [pack(v) for v in value]
        else:
            pool[index] = value
        return index

    for changes in rows or [changes]:
        row = dict(
            id="cup-123",
            kickOffUTC="2026-10-28T19:45:00Z",
            slugTeamName="mens",
            matchStatus="PreMatch",
            competitionName="English League Cup",
            venue="Vitality Stadium",
            teamData=[
                dict(side="Home", teamName="AFC Bournemouth", teamNameInitials="BOU"),
                dict(side="Away", teamName="Aston Villa", teamNameInitials="AVL"),
            ],
        )
        row.update(changes)
        pack(row)
    return (
        '<html><script type="application/json" data-nuxt-data="nuxt-app">'
        + json.dumps(pool)
        + "</script></html>"
    )


class VillaCalendarTests(TestCase):
    def test_official_cup_home_away_and_local_date(self):
        rows = fixtures.parse_club_page(club_page())
        self.assertEqual(rows[0]["competition"], "English League Cup")
        self.assertFalse(rows[0]["is_home"])
        self.assertEqual(rows[0]["kickoff"].hour, 19)
        home = fixtures.parse_club_page(
            club_page(
                teamData=[
                    dict(side="Home", teamName="Aston Villa"),
                    dict(side="Away", teamName="Fulham"),
                ]
            )
        )
        self.assertTrue(home[0]["is_home"])
        summer = fixtures.parse_club_page(club_page(kickOffUTC="2026-08-01T23:30:00Z"))[
            0
        ]
        self.assertEqual(summer["kickoff"].date(), date(2026, 8, 2))
        self.assertEqual(summer["kickoff"].hour, 0)

    def test_changed_status_schema_and_response_limits(self):
        rows = fixtures.parse_club_page(
            club_page(
                {},
                dict(id="postponed", matchStatus="Postponed"),
                dict(id="cancelled", matchStatus="Cancelled"),
            )
        )
        self.assertEqual(len(rows), 1)
        for content in [
            "<html>Unavailable</html>",
            "x" * 2_000_001,
            club_page(kickOffUTC="not-a-date"),
            club_page(slugTeamName="womens"),
        ]:
            with self.assertRaises(ValueError):
                fixtures.parse_club_page(content)
        # Repeated featured-card entries are the same fixture.
        self.assertEqual(len(fixtures.parse_club_page(club_page({}, {}))), 1)

    def test_existing_calendar_entry_wins_despite_different_uid_time_and_spelling(self):
        existing = dict(
            uid="google-event",
            date=TODAY,
            time="19:00-22:00",
            title="Bournemouth vs Aston Villa",
            location="My pub",
        )
        before = deepcopy(existing)
        merged = agenda.merge([existing], [match()])
        self.assertEqual(merged, [before])
        self.assertEqual(existing, before)
        for title in ["AVFC v BOU", "Aston Villa", "Villa match", "Watch Villa"]:
            self.assertEqual(
                len(agenda.merge([dict(existing, title=title)], [match()])), 1, title
            )
        self.assertEqual(len(agenda.merge([], [match(), match()])), 1)
        self.assertEqual(
            len(
                agenda.merge([dict(existing, all_day=True, time="ALL DAY")], [match()])
            ),
            1,
        )

    def test_different_events_teams_dates_and_ticket_travel_are_kept(self):
        for title, day in [
            ("Villa Dental", TODAY),
            ("Villa trains to Bournemouth", TODAY),
            ("Aston Villa women v Bournemouth", TODAY),
            ("Aston Villa v Fulham", TODAY),
            ("Bournemouth v Aston Villa", TODAY + timedelta(days=1)),
        ]:
            event = dict(uid="private", date=day, time="19:45", title=title)
            self.assertEqual(len(agenda.merge([event], [match()])), 2, title)
        self.assertEqual(
            len(
                agenda.merge(
                    [], [match(), match(id="next", home_team="Fulham", home_code="FUL")]
                )
            ),
            2,
        )

    def test_calendar_event_receipt_and_home_trains_do_not_repeat_fixture(self):
        event = agenda.fixture_event(match())
        lines = []
        import textwrap

        print_calendar(
            Mock(),
            [event],
            print_line=lambda *args: None,
            left=lambda p, s: lines.append(s),
            print_wrapped=lambda p, s, width: lines.extend(textwrap.wrap(s, width)),
        )
        self.assertIn("English League Cup", lines)
        self.assertIn("LOCATION: Vitality Stadium", lines)
        self.assertEqual(sum("19:45" in line for line in lines), 1)
        self.assertTrue(all(len(line) <= COLUMNS for line in lines))
        with patch.object(villa, "get_villa_matchday_trains") as trains:
            villa.print_villa_matchday(
                Mock(),
                match(),
                include_trains=True,
                include_match=False,
                left=Mock(),
                centre=Mock(),
                line=Mock(),
                safe_text=str,
            )
            trains.assert_not_called()
        with patch.object(
            villa, "get_villa_matchday_trains", return_value=[]
        ) as trains:
            centre = Mock()
            villa.print_villa_matchday(
                Mock(),
                match(is_home=True),
                include_trains=True,
                include_match=False,
                left=Mock(),
                centre=centre,
                line=Mock(),
                safe_text=str,
            )
            trains.assert_called_once()
            centre.assert_not_called()

    def test_each_source_can_fail_without_hiding_the_other_and_option_disables_villa(
        self,
    ):
        for personal_error, villa_error in [
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ]:
            reset()
            personal_event = dict(
                uid="private", date=TODAY, time="10:00", title="Dentist"
            )
            with (
                TemporaryDirectory() as directory,
                patch("services.api_health.FILE", Path(directory) / "health.json"),
                patch(
                    "services.calendar_locations.apply", side_effect=lambda rows: rows
                ),
                patch(
                    "services.source_cache.get",
                    side_effect=RuntimeError("private URL hidden")
                    if personal_error
                    else lambda *a, **k: [personal_event],
                ),
                patch.object(
                    fixtures,
                    "matches",
                    side_effect=RuntimeError("unavailable")
                    if villa_error
                    else lambda *a, **k: [match()],
                ),
            ):
                rows = agenda.collect("private-url", TODAY, 3)
                self.assertEqual(
                    len(rows), int(not personal_error) + int(not villa_error)
                )
                self.assertEqual(
                    len(snapshot()["Calendar agenda"]["warnings"]),
                    int(personal_error) + int(villa_error),
                )
            reset()
        with (
            patch("services.source_cache.get", return_value=[]),
            patch.object(fixtures, "matches") as fetch,
            patch("services.calendar_locations.apply", return_value=[]),
            patch("receipt.freshness.mark"),
        ):
            agenda.collect("private-url", TODAY, 3, include_villa=False)
            fetch.assert_not_called()

    def test_no_api_key_required_and_cached_schedule_refilters_local_dates(self):
        with (
            TemporaryDirectory() as directory,
            patch("services.source_cache.FILE", Path(directory) / "cache.json"),
            patch("services.api_health.FILE", Path(directory) / "health.json"),
            patch.object(fixtures, "collect_club", return_value=[match()]) as fetch,
        ):
            self.assertEqual(len(fixtures.matches("", today=TODAY)), 1)
            self.assertEqual(fixtures.matches("", today=TODAY + timedelta(days=1)), [])
            fetch.assert_called_once()
        for days in [-1, 32, True]:
            with self.assertRaises(ValueError):
                fixtures.matches(today=TODAY, days=days)

    def test_api_fallback_always_reports_limited_coverage_even_if_empty(self):
        with (
            patch(
                "services.source_cache.get",
                side_effect=[ValueError("club unavailable"), []],
            ),
            patch("receipt.freshness.mark") as mark,
        ):
            self.assertEqual(fixtures.matches("dummy", today=TODAY), [])
            mark.assert_called_with("Villa fixtures", "partial")
