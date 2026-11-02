"""Home-stop feasibility, no teleporting cars, missing data, and private web flows."""

from datetime import date
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock
from flask import Flask, session, request, abort, redirect
from jinja2 import ChoiceLoader, DictLoader
from services import day_travel as travel, travel_routes as provider
from web_control import day_travel as web

DAY = "2026-11-10"
ROOT = Path(__file__).resolve().parents[1]


def event(name, start, end, location):
    return dict(
        uid=name,
        title=name,
        location=location,
        date=DAY,
        start_dt=f"{DAY}T{start}:00+00:00",
        end_dt=f"{DAY}T{end}:00+00:00" if end else None,
    )


def state(next_start="12:00"):
    s = travel.defaults()
    s.update(home="Example home", parking=0)
    events = travel.event_rows(
        [
            event("Appointment A", "10:00", "11:00", "A address"),
            event("Appointment B", next_start, "13:00", "B address"),
        ],
        DAY,
    )
    s["days"][DAY] = dict(events=events, overrides={})
    for index, address in enumerate([s["home"], "A address", "B address"]):
        s["places"][travel.key(address)] = dict(
            address=address, point=[52 + index * 0.01, -1.9], confirmed=True, choices=[]
        )
    return s


def route(a, b, mode):
    return dict(
        minutes=10, geometry=[a["point"], b["point"]], source="Test route estimate"
    )


class TravelPlannerTests(TestCase):
    def test_home_stop_includes_buffer_both_legs_and_useful_home_time(self):
        s = state()
        result = travel.build(s, DAY, route)
        self.assertIn("30 minutes at home", result["visits"][1]["message"])
        self.assertEqual(len(result["legs"]), 4)
        s = state("11:59")
        result = travel.build(s, DAY, route)
        self.assertIn("Go direct", result["visits"][1]["message"])
        self.assertIn("29 minutes", result["visits"][1]["message"])
        self.assertEqual(len(result["legs"]), 3)
        s["days"][DAY]["overrides"][s["days"][DAY]["events"][1]["id"]] = dict(
            mode="auto", via="home", end="", skip=False
        )
        self.assertTrue(
            any(
                "could not be verified" in x
                for x in travel.build(s, DAY, route)["warnings"]
            )
        )

    def test_car_is_left_when_walking_and_collected_before_driving_again(self):
        s = state()
        second = s["days"][DAY]["events"][1]
        s["days"][DAY]["overrides"][second["id"]] = dict(
            mode="walking", via="direct", end="", skip=False
        )
        result = travel.build(s, DAY, route)
        self.assertEqual(result["visits"][1]["car_at"], "Appointment A")
        legs = result["legs"]
        self.assertEqual(
            [x["mode"] for x in legs], ["driving", "walking", "walking", "driving"]
        )
        self.assertEqual(legs[-2]["destination"]["label"], "Appointment A")
        self.assertIn("collect your parked car", legs[-1]["note"])
        s["car"] = False
        result = travel.build(s, DAY, route)
        self.assertTrue(all(x["mode"] == "walking" for x in result["legs"]))
        self.assertEqual(result["car_at"], "No car available")

    def test_missing_end_locations_or_transit_times_cannot_prove_home_stop(self):
        s = state()
        s["mode"] = "transit"
        call = Mock(
            side_effect=AssertionError("Transit must not query a driving profile")
        )
        result = travel.build(s, DAY, call)
        call.assert_not_called()
        self.assertTrue(all(x["minutes"] is None for x in result["legs"]))
        self.assertTrue(all(x["depart"] is None for x in result["legs"]))
        self.assertTrue(any("unknown" in x for x in result["warnings"]))
        s = state()
        s["days"][DAY]["events"][0]["end"] = None
        result = travel.build(s, DAY, route)
        self.assertIn("cannot be assessed", result["visits"][1]["message"])
        self.assertTrue(any("finish time unknown" in x for x in result["warnings"]))
        s["home"] = ""
        s["days"][DAY]["events"][0]["address"] = ""
        self.assertIsNone(travel.build(s, DAY, route)["legs"][0]["minutes"])

    def test_late_journey_does_not_depart_before_previous_event_ends(self):
        result = travel.build(state("10:50"), DAY, route)
        leg = result["legs"][1]
        self.assertEqual(travel.when(leg["depart"]).hour, 11)
        self.assertTrue(any("overlap" in w for w in result["warnings"]))
        self.assertTrue(any("exceeds" in w for w in result["warnings"]))

    def test_manual_durations_are_directional_and_override_unknown_routes(self):
        s = state()
        s["mode"] = "transit"
        home = travel.place(s["home"], s)
        a = travel.place("A address", s)
        s["manual"][travel.route_key(home, a, "transit")] = 27
        result = travel.build(s, DAY, Mock(return_value=None))
        self.assertEqual(result["legs"][0]["minutes"], 27)
        self.assertIsNone(result["legs"][-1]["minutes"])
        self.assertEqual(result["legs"][0]["source"], "Your duration estimate")

    def test_all_day_and_online_skips_do_not_create_timed_journeys(self):
        s = state()
        e = s["days"][DAY]["events"][1]
        e.update(all_day=True, start=None, end=None)
        result = travel.build(s, DAY, route)
        self.assertEqual(len(result["visits"]), 1)
        self.assertTrue(any("untimed" in w for w in result["warnings"]))
        s["days"][DAY]["overrides"][e["id"]] = dict(skip=True)
        self.assertNotIn(
            "B address", [x["address"] for x in travel.build(s, DAY, route)["points"]]
        )

    def test_bad_coordinates_times_modes_and_corrupt_private_state_fail_validation(
        self,
    ):
        for coords in [[float("nan"), 1], [100, 1], [0, 181], [True, 1]]:
            with self.assertRaises(ValueError):
                travel.point(coords)
        for modify in [
            lambda s: s.update(buffer=500),
            lambda s: s["manual"].update(bad=10),
            lambda s: s["days"][DAY]["events"][0].update(start="bad"),
        ]:
            s = state()
            modify(s)
            with self.assertRaises(ValueError):
                travel.validate(s)


class TravelClockTests(TestCase):
    def test_autumn_clock_change_orders_events_by_actual_instant(self):
        rows = travel.event_rows(
            [
                dict(
                    uid="second",
                    title="Second",
                    location="B",
                    start_dt="2026-10-25T01:15:00+00:00",
                    end_dt="2026-10-25T02:00:00+00:00",
                ),
                dict(
                    uid="first",
                    title="First",
                    location="A",
                    start_dt="2026-10-25T01:45:00+01:00",
                    end_dt="2026-10-25T01:45:00+00:00",
                ),
            ],
            "2026-10-25",
        )
        self.assertEqual([e["title"] for e in rows], ["First", "Second"])
        self.assertIsNotNone(rows[0]["end"])


class InlineThread:
    def __init__(self, target, args, **kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class TravelWebTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for module, field, value in [
            (travel, "FILE", Path(self.tmp.name) / "data" / "day_travel.json"),
            (provider, "CACHE", Path(self.tmp.name) / "cache"),
        ]:
            p = patch.object(module, field, value)
            p.start()
            self.addCleanup(p.stop)
        web.JOB.clear()
        self.addCleanup(web.JOB.clear)
        self.app = Flask(
            __name__, template_folder=str(ROOT / "web_control" / "templates")
        )
        self.app.secret_key = "fixture"
        self.app.jinja_loader = ChoiceLoader(
            [
                DictLoader({"navigation.html": "", "favicon.html": ""}),
                self.app.jinja_loader,
            ]
        )
        self.app.jinja_env.globals["csrf_token"] = lambda: session["csrf_token"]

        @self.app.before_request
        def csrf():
            if request.method == "POST" and request.form.get(
                "csrf_token"
            ) != session.get("csrf_token"):
                abort(403)

        def login(fn):
            @wraps(fn)
            def wrapped(*a, **k):
                return (
                    fn(*a, **k) if session.get("authenticated") else redirect("/login")
                )

            return wrapped

        self.app.add_url_rule(
            "/calendar-map", endpoint="calendar_map", view_func=lambda: "Calendar"
        )
        web.register(
            self.app,
            login,
            lambda day: ([event("Appointment A", "10:00", "11:00", "A address")], []),
        )
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s.update(authenticated=True, csrf_token="test")

        # Test the same deterministic fixture date while retaining the year-range validation.
        p = patch("receipt.local_time.uk_today", return_value=date.fromisoformat(DAY))
        p.start()
        self.addCleanup(p.stop)

    def post(self, path, **data):
        return self.client.post(
            "/day-travel/" + path, data=dict(day=DAY, csrf_token="test", **data)
        )

    def test_private_page_home_editor_csrf_and_no_network_on_get(self):
        with patch.object(provider, "locate") as locate:
            response = self.client.get("/day-travel?day=" + DAY)
            self.assertEqual(response.status_code, 200)
            locate.assert_not_called()
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(
            self.client.post(
                "/day-travel/settings", data={"home": "Private home"}
            ).status_code,
            403,
        )
        self.post(
            "settings",
            home="Private home",
            mode="walking",
            buffer="10",
            home_minutes="30",
            parking="5",
        )
        saved = travel.store().read()
        self.assertEqual(saved["home"], "Private home")
        self.assertFalse(saved["car"])
        self.assertEqual(travel.FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.client.get("/day-travel?day=bad").status_code, 400)
        with self.client.session_transaction() as s:
            s.clear()
        self.assertEqual(self.client.get("/day-travel").status_code, 302)
        self.assertEqual(self.client.get("/day-travel/status").status_code, 302)

    def test_background_find_confirm_plan_and_clear_including_provider_cache(self):
        self.post(
            "settings",
            home="Private home",
            mode="driving",
            car="on",
            buffer="10",
            home_minutes="30",
            parking="5",
        )
        with (
            patch.object(web, "Thread", InlineThread),
            patch.object(
                provider,
                "locate",
                return_value=[dict(point=[52.45, -1.9], label="Fixture place")],
            ),
        ):
            self.post("run", action="locations")
        self.assertEqual(web.JOB["state"], "complete")
        data = travel.store().read()
        for identifier in data["places"]:
            self.post("place", place=identifier, choice="0")
        with (
            patch.object(web, "Thread", InlineThread),
            patch.object(provider, "route", side_effect=route),
        ):
            self.post("run", action="plan")
        self.assertEqual(web.JOB["state"], "complete")
        response = self.client.get("/day-travel?day=" + DAY)
        self.assertEqual(response.status_code, 200)
        self.assertIn("travel-map-data", response.get_data(as_text=True))
        self.assertIn("Check directions", response.get_data(as_text=True))
        status = self.client.get("/day-travel/status").get_json()
        self.assertNotIn("owner", status)
        self.assertNotIn("token", status)
        provider.CACHE.mkdir()
        (provider.CACHE / "example.json").write_text("Private cached place")
        web.JOB["state"] = "running"
        self.assertEqual(self.post("clear", confirm="on").status_code, 409)
        web.JOB["state"] = "complete"
        self.post("clear", confirm="on")
        self.assertEqual(travel.store().read()["home"], "")
        self.assertFalse(list(provider.CACHE.glob("*.json")))

    def test_duration_override_removal_and_event_controls_invalidate_old_plan(self):
        travel.store().update(lambda s: s.update(state()))
        data = travel.store().read()
        a = travel.key(data["home"])
        b = travel.key("A address")
        self.post("duration", origin=a, destination=b, mode="transit", minutes="25")
        self.assertEqual(travel.store().read()["manual"][a + "|" + b + "|transit"], 25)
        self.post("duration", origin=a, destination=b, mode="transit", remove="on")
        self.assertEqual(travel.store().read()["manual"], {})
        e = data["days"][DAY]["events"][0]
        self.post(
            "event", event=e["id"], mode="walking", via="direct", end="11:15", skip="on"
        )
        self.assertTrue(
            travel.store().read()["days"][DAY]["overrides"][e["id"]]["skip"]
        )


class TravelProviderTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(provider, "CACHE", Path(self.tmp.name) / "cache")
        p.start()
        self.addCleanup(p.stop)

    def test_cached_confirmed_coordinate_routes_use_each_correct_profile(self):
        a = dict(point=[52.4, -1.9])
        b = dict(point=[52.5, -1.8])
        data = dict(
            code="Ok",
            routes=[
                dict(
                    duration=601,
                    geometry=dict(coordinates=[[-1.9, 52.4], [-1.8, 52.5]]),
                )
            ],
        )
        with patch.object(provider, "fetch", return_value=data) as fetch:
            for mode, profile in [
                ("walking", "foot"),
                ("driving", "car"),
                ("cycling", "bike"),
            ]:
                result = provider.route(a, b, mode, 999999999)
                self.assertEqual(result["minutes"], 11)
                self.assertIn("/routed-" + profile + "/", fetch.call_args.args[0])
                self.assertEqual(result["geometry"], [a["point"], b["point"]])
                provider.route(a, b, mode, 999999999)
            self.assertEqual(fetch.call_count, 3)
        with patch.object(provider, "fetch") as fetch:
            self.assertIsNone(provider.route(a, b, "transit", 999999999))
            fetch.assert_not_called()

    def test_geocoder_choices_are_bounded_and_do_not_silently_confirm_first_match(self):
        data = dict(
            features=[
                dict(
                    geometry=dict(coordinates=[-1.9, 52.4]),
                    properties=dict(name="Example place", city="Birmingham"),
                )
                for _ in range(5)
            ]
        )
        with patch.object(provider, "fetch", return_value=data):
            rows = provider.locate("Example address", 999999999)
        self.assertEqual(len(rows), 3)
        self.assertNotIn("confirmed", rows[0])
        self.assertEqual(rows[0]["point"], [52.4, -1.9])

    def test_provider_requests_have_verified_https_no_redirects_and_size_deadline_limits(
        self,
    ):
        response = Mock(status_code=302)
        client = Mock()
        client.get.return_value = response
        with patch.object(provider.requests, "Session") as session:
            session.return_value.__enter__.return_value = client
            with self.assertRaises(ValueError):
                provider.fetch(
                    "https://routing.openstreetmap.de/example",
                    {},
                    __import__("time").monotonic() + 10,
                )
        kwargs = client.get.call_args.kwargs
        self.assertFalse(kwargs["allow_redirects"])
        self.assertFalse(client.trust_env)
        self.assertIn(
            "ThermalReceiptPrinterDailyTasks", kwargs["headers"]["User-Agent"]
        )
        self.assertNotIn("verify", kwargs)
        with patch.dict("os.environ", {"RECEIPT_TRAVEL_ROUTER": "http://example.test"}):
            with self.assertRaises(ValueError):
                provider.endpoint("RECEIPT_TRAVEL_ROUTER", "https://example.test")
