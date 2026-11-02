"""Automatic address handling, walk-first choice and actual bus/train timing boundaries."""

from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock, patch
from services import (
    day_travel as travel,
    travel_geocoding as geo,
    travel_transit as transit,
    travel_routes as provider,
)
from test_day_travel import state, DAY, route, InlineThread
import test_day_travel as baseline


def bus(a, b, arrive_by=None, depart_after=None):
    dep = (
        arrive_by - timedelta(minutes=20)
        if arrive_by
        else depart_after + timedelta(minutes=5)
    )
    arr = dep + timedelta(minutes=20)
    return dict(
        minutes=20,
        departure=dep.isoformat(),
        arrival=arr.isoformat(),
        steps=[
            dict(
                mode="bus",
                line="45",
                origin="Example stop",
                destination="Example destination",
                headsign="City",
                depart=dep.strftime("%H:%M"),
                arrive=arr.strftime("%H:%M"),
            )
        ],
        source="Fixture scheduled transit",
        acknowledgements="Fixture data",
        geometry=[],
    )


class AutomaticGeocodingTests(TestCase):
    def test_long_venue_address_retries_street_and_uses_matching_postcode_automatically(
        self,
    ):
        address = "Example Community Venue, 10 Example Rd, Birmingham B1 1AA, UK"
        choices = [
            dict(
                point=[52.42, -1.93],
                label="10 Example Road, Birmingham, B1 1AA",
                match=dict(postcode="B1 1AA", housenumber="10"),
            )
        ]
        with patch.object(provider, "locate", side_effect=[[], choices]) as locate:
            result = provider.resolve(address, 999999999)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["point"], choices[0]["point"])
        self.assertEqual(
            locate.call_args.args[0], "10 Example Rd, Birmingham B1 1AA, UK"
        )

    def test_postcode_fallback_is_marked_approximate_and_conflicting_houses_not_silently_used(
        self,
    ):
        address = "10 Example Road, B1 1AA"
        bad = [
            dict(
                point=[52.4, -1.9],
                label="99 Example Road B1 1AA",
                match=dict(postcode="B1 1AA", housenumber="99"),
            )
        ]
        self.assertIsNone(geo.select(address, bad))
        with (
            patch.object(provider, "locate", return_value=[]),
            patch.object(
                provider,
                "cached",
                return_value=dict(
                    result=dict(postcode="B1 1AA", latitude=52.42, longitude=-1.93)
                ),
            ),
        ):
            result = provider.resolve(address, 999999999)
        self.assertTrue(result["confirmed"])
        self.assertIn("postcode centre", result["accuracy"])

    def test_ambiguous_distant_results_or_wrong_postcodes_do_not_invent_a_pin(self):
        self.assertIsNone(
            geo.select(
                "Example library",
                [
                    dict(point=[52, -1], label="Example library"),
                    dict(point=[54, -1], label="Example library"),
                ],
            )
        )
        self.assertIsNone(geo.select("B1 1AA", [dict(point=[1, 2], label="B31 1AA")]))


class AutomaticJourneyTests(TestCase):
    def test_short_walk_preferred_even_when_car_and_public_transport_available(self):
        s = state()
        s["mode"] = "auto"
        public = Mock(side_effect=bus)
        result = travel.build(s, DAY, route, transit=public)
        self.assertTrue(all(x["mode"] == "walking" for x in result["legs"]))
        public.assert_not_called()
        self.assertEqual(result["car_at"], "Home")
        self.assertIn("Walking preferred", result["legs"][0]["note"])

    def test_longer_walk_uses_real_transit_schedule_and_leaves_car_at_home(self):
        s = state()
        s["mode"] = "auto"
        result = travel.build(
            s,
            DAY,
            lambda a, b, m: dict(minutes=40, geometry=[], source="Walking estimate"),
            transit=bus,
        )
        self.assertTrue(all(x["mode"] == "transit" for x in result["legs"]))
        self.assertEqual(result["car_at"], "Home")
        first = result["legs"][0]
        self.assertEqual(travel.when(first["depart"]).strftime("%H:%M"), "09:30")
        self.assertEqual(first["steps"][0]["line"], "45")
        self.assertEqual(
            travel.when(result["legs"][-1]["depart"]).strftime("%H:%M"), "13:05"
        )

    def test_bus_cannot_be_shifted_later_to_fit_previous_event_or_fabricate_home_gap(
        self,
    ):
        s = state()
        s["mode"] = "transit"

        def scheduled(a, b, arrive_by=None, depart_after=None):
            if arrive_by:
                return bus(a, b, arrive_by, depart_after)
            trip = bus(a, b, None, depart_after + timedelta(minutes=45))
            return trip

        result = travel.build(s, DAY, route, transit=scheduled)
        self.assertIn("cannot be assessed", result["visits"][1]["message"])
        s = state("11:20")
        s["mode"] = "transit"
        result = travel.build(s, DAY, route, transit=bus)
        self.assertIsNone(result["legs"][1]["minutes"])
        self.assertIsNone(result["legs"][1]["depart"])

    def test_short_walk_that_would_miss_event_is_not_preferred_over_usable_transit(
        self,
    ):
        s = state("11:25")
        s["mode"] = "auto"
        s["walk_minutes"] = 25

        def quick_bus(a, b, arrive_by=None, depart_after=None):
            info = bus(a, b, arrive_by, depart_after)
            if arrive_by:
                info["departure"] = (arrive_by - timedelta(minutes=5)).isoformat()
                info["minutes"] = 5
            return info

        result = travel.build(
            s,
            DAY,
            lambda a, b, m: dict(minutes=20, geometry=[], source="Walk estimate"),
            transit=quick_bus,
        )
        self.assertEqual(result["legs"][1]["mode"], "transit")


class TransitAdapterTests(TestCase):
    def response(self):
        return dict(
            source="Scheduled test",
            acknowledgements="Test attribution",
            routes=[
                dict(
                    departure_datetime=DAY + "T09:10:00+00:00",
                    arrival_datetime=DAY + "T09:40:00+00:00",
                    route_parts=[
                        dict(
                            mode="foot",
                            from_point_name="Home",
                            to_point_name="Bus stop",
                        ),
                        dict(
                            mode="bus",
                            line_name="45",
                            from_point_name="Bus stop",
                            to_point_name="Library",
                            departure_time="09:20",
                            arrival_time="09:35",
                        ),
                    ],
                )
            ],
        )

    def test_documented_api_uses_header_auth_and_correct_day_arrival_type(self):
        a = dict(point=[52.4, -1.9])
        b = dict(point=[52.5, -1.8])
        at = travel.when(DAY + "T09:50:00+00:00")
        with patch.object(provider, "cached", return_value=self.response()) as fetch:
            result = transit.route(
                a, b, 999999999, ("private-test-id", "private-test-key"), arrive_by=at
            )
        self.assertEqual(result["minutes"], 30)
        args, kwargs = fetch.call_args
        self.assertEqual(args[0], "https://transportapi.com/v3/uk/public_journey.json")
        self.assertEqual(args[1]["journey_time_type"], "arrive_by")
        self.assertEqual(args[1]["from"], "lonlat:-1.900000,52.400000")
        self.assertNotIn("private-test-key", str(args))
        self.assertEqual(kwargs["headers"]["X-App-Key"], "private-test-key")
        self.assertNotIn("private-test-key", str(result))
        self.assertEqual(result["steps"][1]["line"], "45")

    def test_rejects_departures_before_previous_finish_missing_offsets_and_late_arrivals(
        self,
    ):
        data = self.response()
        finish = travel.when(DAY + "T09:15:00+00:00")
        self.assertIsNone(transit.parse(data, depart_after=finish))
        self.assertIsNone(
            transit.parse(data, arrive_by=travel.when(DAY + "T09:30:00+00:00"))
        )
        data["routes"][0]["departure_datetime"] = DAY + "T09:10:00"
        self.assertIsNone(transit.parse(data))

    def test_missing_credentials_or_unknown_provider_status_never_becomes_zero_minutes(
        self,
    ):
        with patch.object(provider, "cached") as fetch:
            self.assertIsNone(
                transit.route(dict(point=[1, 2]), dict(point=[2, 3]), 999999, ("", ""))
            )
            fetch.assert_not_called()
        self.assertIsNone(transit.parse(dict(routes=[])))


class AutomaticWebTests(TestCase):
    setUp = baseline.TravelWebTests.setUp
    post = baseline.TravelWebTests.post

    def test_one_action_resolves_and_plans_without_coordinate_confirmation(self):
        self.post(
            "settings",
            home="Private home",
            mode="auto",
            walk_minutes="25",
            car="on",
            buffer="10",
            home_minutes="30",
            parking="5",
        )

        def resolved(address, deadline):
            index = 0 if address == "Private home" else 1
            return dict(
                address=address,
                point=[52.4 + index * 0.01, -1.9],
                choices=[],
                confirmed=True,
                source="Automatic address match",
                accuracy="Matched address",
            )

        with (
            patch.object(baseline.web, "Thread", InlineThread),
            patch.object(provider, "resolve", side_effect=resolved),
            patch.object(
                provider, "route", side_effect=lambda a, b, m, deadline: route(a, b, m)
            ),
        ):
            self.assertEqual(self.post("run", action="auto").status_code, 302)
        self.assertEqual(baseline.web.JOB["state"], "complete")
        saved = travel.store().read()
        self.assertTrue(all(p["confirmed"] for p in saved["places"].values()))
        self.assertTrue(saved["days"][DAY]["plan"]["legs"])
        html = self.client.get("/day-travel?day=" + DAY).get_data(as_text=True)
        self.assertIn("Plan my day", html)
        self.assertIn("Located automatically", html)
        self.assertNotIn("Map point missing", html)
