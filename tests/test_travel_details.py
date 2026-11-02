"""At-home calendar time, inline street directions and scheduled timetable presentation."""

from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock, patch
from services import (
    day_travel as travel,
    travel_routes as provider,
    travel_transit as transit,
    travel_instructions as instructions,
)
import test_day_travel as base


class AtHomeTests(TestCase):
    def test_locationless_events_stay_home_and_do_not_query_routes(self):
        s = base.state()
        s["days"][base.DAY]["events"] = travel.event_rows(
            [
                base.event("Home call", "10:00", "11:00", ""),
                base.event("Home appointment", "11:00", "12:00", None),
            ],
            base.DAY,
        )
        street = Mock(side_effect=AssertionError("No trip needed"))
        public = Mock(side_effect=AssertionError("No service needed"))
        result = travel.build(s, base.DAY, street, transit=public)
        self.assertEqual(result["legs"], [])
        self.assertTrue(all(v["home_assumed"] for v in result["visits"]))
        self.assertTrue(all("Stay at home" in v["message"] for v in result["visits"]))
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["points"]), 1)
        street.assert_not_called()
        public.assert_not_called()

    def test_blank_location_requires_return_home_and_still_reserves_event_duration(
        self,
    ):
        s = base.state()
        s["days"][base.DAY]["events"] = travel.event_rows(
            [
                base.event("Away appointment", "10:00", "11:00", "A address"),
                base.event("At-home appointment", "11:30", "12:00", ""),
                base.event("Next appointment", "12:10", "13:00", "B address"),
            ],
            base.DAY,
        )
        result = travel.build(s, base.DAY, base.route)
        home = result["visits"][1]
        self.assertTrue(home["home_assumed"])
        self.assertIn("Return home", home["message"])
        self.assertEqual(home["location"]["id"], travel.key(s["home"]))
        outbound = next(
            leg
            for leg in result["legs"]
            if leg["destination"]["label"] == "Next appointment"
        )
        self.assertGreaterEqual(travel.when(outbound["depart"]).hour, 12)
        self.assertTrue(any("exceeds" in warning for warning in result["warnings"]))

    def test_at_home_event_does_not_leave_house_just_to_collect_parked_car(self):
        s = base.state()
        s["days"][base.DAY]["events"] = travel.event_rows(
            [
                base.event("Away A", "10:00", "10:30", "A address"),
                base.event("Walk home", "11:00", "11:15", s["home"]),
                base.event("Home call", "11:15", "12:00", ""),
            ],
            base.DAY,
        )
        events = s["days"][base.DAY]["events"]
        s["days"][base.DAY]["overrides"][events[1]["id"]] = dict(
            mode="walking", via="direct", end="", skip=False
        )
        result = travel.build(s, base.DAY, base.route)
        self.assertEqual(len(result["legs"]), 2)
        self.assertEqual(result["car_at"], "Away A")
        self.assertIn("Stay at home", result["visits"][-1]["message"])


class DirectionsTests(TestCase):
    def test_directions_use_reported_street_turn_roundabout_exit_and_arrival(self):
        route = dict(
            legs=[
                dict(
                    steps=[
                        dict(
                            name="Example Road",
                            distance=120,
                            maneuver=dict(type="depart", bearing_after=0),
                        ),
                        dict(
                            name="Other Road",
                            distance=1000,
                            maneuver=dict(type="turn", modifier="left"),
                        ),
                        dict(
                            name="Station Road",
                            distance=40,
                            maneuver=dict(type="roundabout", exit=2),
                        ),
                        dict(
                            distance=0, maneuver=dict(type="arrive", modifier="right")
                        ),
                    ]
                )
            ]
        )
        rows, truncated = instructions.build(route)
        self.assertFalse(truncated)
        self.assertIn("heading north", rows[0]["instruction"])
        self.assertEqual(rows[0]["distance"], "120 m")
        self.assertEqual(rows[1]["instruction"], "Turn left onto Other Road")
        self.assertEqual(rows[1]["distance"], "1.0 km")
        self.assertIn("exit 2", rows[2]["instruction"])
        self.assertIn("on the right", rows[3]["instruction"])
        many = deepcopy(route)
        many["legs"][0]["steps"] *= 60
        rows, truncated = instructions.build(many)
        self.assertEqual(len(rows), 200)
        self.assertTrue(truncated)
        self.assertEqual(instructions.distance(float("nan")), "")
        self.assertEqual(instructions.distance(10**500), "")

    def test_provider_requests_steps_and_engine_retains_directions(self):
        data = dict(
            code="Ok",
            routes=[
                dict(
                    duration=600,
                    geometry=dict(coordinates=[[-1.9, 52.4], [-1.8, 52.5]]),
                    legs=[
                        dict(
                            steps=[
                                dict(
                                    name="Example Street",
                                    distance=100,
                                    maneuver=dict(type="depart"),
                                )
                            ]
                        )
                    ],
                )
            ],
        )
        with patch.object(provider, "cached", return_value=data) as fetch:
            found = provider.route(
                dict(point=[52.4, -1.9]), dict(point=[52.5, -1.8]), "walking", 999999999
            )
        self.assertEqual(fetch.call_args.args[1]["steps"], "true")
        self.assertIn("Example Street", found["directions"][0]["instruction"])
        s = base.state()
        result = travel.build(s, base.DAY, lambda *args: found)
        self.assertTrue(result["legs"][0]["directions"])

    def test_transit_step_full_timestamps_retained_for_midnight_and_timezone_labels(
        self,
    ):
        raw = dict(
            source="Test",
            routes=[
                dict(
                    departure_datetime="2026-11-10T23:50:00Z",
                    arrival_datetime="2026-11-11T00:20:00Z",
                    route_parts=[
                        dict(
                            mode="bus",
                            line_name="45",
                            departure_datetime="2026-11-10T23:55:00Z",
                            arrival_datetime="2026-11-11T00:15:00Z",
                        )
                    ],
                )
            ],
        )
        info = transit.parse(raw)
        self.assertEqual(info["steps"][0]["depart_at"], "2026-11-10T23:55:00+00:00")
        self.assertEqual(info["steps"][0]["arrive_at"], "2026-11-11T00:15:00+00:00")


class ManualDirectionsTests(TestCase):
    def test_manual_street_duration_keeps_provider_directions_without_replacing_minutes(
        self,
    ):
        s = base.state()
        home = travel.place(s["home"], s)
        a = travel.place("A address", s)
        s["manual"][travel.route_key(home, a, "driving")] = 27
        result = travel.build(
            s,
            base.DAY,
            lambda *args: dict(
                minutes=10,
                geometry=[],
                source="Provider",
                directions=[dict(instruction="Turn left", distance="100 m")],
            ),
        )
        self.assertEqual(result["legs"][0]["minutes"], 27)
        self.assertEqual(result["legs"][0]["directions"][0]["instruction"], "Turn left")


class InlineDetailsWebTests(TestCase):
    setUp = base.TravelWebTests.setUp
    post = base.TravelWebTests.post

    def test_page_shows_departure_arrival_directions_and_timetable_without_external_button(
        self,
    ):
        s = base.state()
        s["days"][base.DAY]["plan"] = travel.build(
            s,
            base.DAY,
            lambda a, b, m: dict(
                minutes=10,
                geometry=[],
                source="Test route",
                directions=[
                    dict(instruction="Turn left onto Example Road", distance="100 m")
                ],
            ),
        )
        s["days"][base.DAY]["plan"]["checked"] = base.DAY + "T09:00:00+00:00"
        leg = s["days"][base.DAY]["plan"]["legs"][1]
        leg.update(
            mode="transit",
            steps=[
                dict(
                    mode="bus",
                    line="45",
                    origin="Example stop",
                    destination="Example station",
                    depart="11:10",
                    arrive="11:20",
                    headsign="City",
                )
            ],
        )
        travel.store().update(lambda v: v.update(s))
        response = self.client.get("/day-travel?day=" + base.DAY)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for value in [
            "Departure",
            "Arrival",
            "Turn left onto Example Road",
            "Journey timetable",
            "Example stop",
            "11:10",
        ]:
            self.assertIn(value, html)
        self.assertNotIn("Google Maps", html)
