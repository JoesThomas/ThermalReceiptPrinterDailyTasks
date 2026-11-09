"""Daily planning remains local, explainable, bounded and subordinate to deadlines."""

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from actions import checklists, personal_helper as helper
from meals import resource_planning as resources
from meals.ingredients import aggregate
from receipt.local_time import UK

NOW = datetime(2026, 11, 2, 8, tzinfo=UK)
DAY = NOW.date().isoformat()


def task(identifier, **kw):
    return dict(
        id=identifier,
        title=identifier,
        kind="tasks",
        done=False,
        source="local",
        done_on=None,
        **kw,
    )


def event(name, a=10, b=11, address=""):
    return dict(
        title=name,
        location=address,
        start_dt=NOW.replace(hour=a).isoformat(),
        end_dt=NOW.replace(hour=b).isoformat() if b else None,
    )


def travel_day(events):
    return dict(
        events=events,
        plan=dict(
            day=DAY,
            checked=NOW.isoformat(),
            points=[dict(id="home", label="Home")],
            warnings=[],
            legs=[
                dict(
                    mode="walking",
                    depart=NOW.replace(hour=9, minute=40).isoformat(),
                    arrive=NOW.replace(hour=9, minute=55).isoformat(),
                    origin=dict(id="home"),
                    destination=dict(id="venue", label="Appointment"),
                    geometry=[[52, -1.9], [52.01, -1.9]],
                ),
                dict(
                    mode="walking",
                    depart=NOW.replace(hour=11).isoformat(),
                    arrive=NOW.replace(hour=11, minute=20).isoformat(),
                    origin=dict(id="venue"),
                    destination=dict(id="home", label="Home"),
                    geometry=[[52.01, -1.9], [52, -1.9]],
                ),
            ],
        ),
    )


class HelperTests(TestCase):
    def test_calendar_and_travel_reserved_before_home_tasks(self):
        events = [event("Therapy", address="Example place")]
        settings = helper.defaults()
        settings["tasks"] = {"one": dict(minutes=120), "two": dict(minutes=120)}
        view = helper.build(
            [task("one"), task("two")], events, travel_day(events), settings, NOW
        )
        slots = view["reservations"]
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0]["start"].hour, 11)
        self.assertEqual(slots[0]["start"].minute, 20)
        self.assertLessEqual(slots[0]["end"], slots[1]["start"])
        self.assertEqual(view["departure"]["at"].minute, 40)
        self.assertTrue(all(s["context"] == "home" for s in slots))

    def test_locationless_event_blocks_time_without_inventing_outing(self):
        view = helper.build(
            [task("a")], [event("Call")], settings=helper.defaults(), now=NOW
        )
        self.assertEqual(view["take"], [])
        self.assertEqual(
            [(w["start"].hour, w["end"].hour, w["context"]) for w in view["windows"]],
            [(8, 10, "home"), (11, 20, "home")],
        )

    def test_unknown_finish_blocks_rest_of_day_and_stale_plan_is_rejected(self):
        events = [event("Appointment", b=None, address="Venue")]
        saved = travel_day(events)
        saved["plan"]["checked"] = (NOW - timedelta(days=2)).isoformat()
        view = helper.build([], events, saved, helper.defaults(), NOW)
        self.assertIsNone(view["departure"])
        self.assertEqual(len(view["windows"]), 1)
        self.assertEqual(view["windows"][0]["end"].minute, 30)
        self.assertTrue(any("Finish time unknown" in w for w in view["warnings"]))

    def test_removed_event_does_not_reappear_from_saved_plan(self):
        view = helper.build(
            [], [], travel_day([event("Removed")]), helper.defaults(), NOW
        )
        self.assertIsNone(view["departure"])
        self.assertEqual(view["windows"][0]["minutes"], 720)
        self.assertTrue(view["warnings"])

    def test_lighter_day_keeps_deadlines_and_essential_even_if_hidden_deferred(self):
        settings = helper.defaults()
        settings["lighter"] = [DAY]
        settings["tasks"] = {
            "urgent": dict(hidden=True, defer_until="2026-11-04", effort="high"),
            "essential": dict(essential=True, hidden=True),
            "optional": dict(effort="high"),
        }
        view = helper.build(
            [
                task("urgent", due=DAY),
                task("essential"),
                task("optional"),
                task("easy"),
            ],
            [],
            settings=settings,
            now=NOW,
        )
        self.assertEqual({t["id"] for t in view["urgent"]}, {"urgent", "essential"})
        self.assertEqual(len(view["priorities"]), 2)
        self.assertNotIn("optional", [t["id"] for t in view["pending"]])
        self.assertTrue(
            all(t["minutes"] == 5 and t["timebox"] for t in view["pending"])
        )

    def test_deferrals_suggest_smaller_step_but_do_not_duplicate_main_tasks(self):
        settings = helper.defaults()
        settings["tasks"] = {
            "a": dict(
                first_seen="2026-10-20",
                deferrals=["2026-10-21", "2026-10-23", "2026-10-25"],
                steps=["Find supplies", "Do it"],
                step_done=[0],
            )
        }
        tasks = [task("a")]
        original = deepcopy(tasks)
        view = helper.build(tasks, [], settings=settings, now=NOW)
        self.assertEqual(view["nudges"][0]["deferrals"], 3)
        self.assertEqual(view["priorities"][0]["next_step"], "Do it")
        self.assertEqual(tasks, original)

    def test_rules_count_back_from_event_and_weather_only_for_correct_day(self):
        settings = helper.defaults()
        settings["rules"] = [
            dict(
                id="r",
                match="therapy",
                lead_hours=24,
                take=["Notebook"],
                prepare=["Check questions"],
            )
        ]
        settings["weather"] = dict(day=DAY, rain=80, low=5)
        events = [event("Therapy", address="Venue")]
        tomorrow = event("Therapy follow-up", address="Venue")
        for key in ("start_dt", "end_dt"):
            tomorrow[key] = (
                datetime.fromisoformat(tomorrow[key]) + timedelta(days=1)
            ).isoformat()
        view = helper.build([], events + [tomorrow], settings=settings, now=NOW)
        self.assertIn("Notebook", view["take"])
        self.assertIn("Umbrella / raincoat", view["take"])
        self.assertIn("Warm layer", view["take"])
        self.assertEqual(
            next(p for p in view["preparation"] if p["title"] == "Check questions")[
                "by"
            ].hour,
            10,
        )
        settings["weather"]["day"] = "2026-11-01"
        self.assertNotIn(
            "Umbrella / raincoat",
            helper.build([], events, settings=settings, now=NOW)["take"],
        )

    def test_errand_matches_geometry_but_not_transit_or_far_away(self):
        events = [event("Therapy", address="Venue")]
        saved = travel_day(events)
        settings = helper.defaults()
        settings["tasks"] = {"Shop": dict(context="outside")}
        settings["errands"] = {
            "Shop": dict(
                address="Example shop",
                point=[52.005, -1.9005],
                hours="Check Monday hours",
            )
        }
        view = helper.build([task("Shop")], events, saved, settings, NOW)
        self.assertEqual(len(view["errands"]), 1)
        for leg in saved["plan"]["legs"]:
            leg["mode"] = "transit"
        self.assertEqual(
            helper.build([task("Shop")], events, saved, settings, NOW)["errands"], []
        )
        self.assertGreater(
            helper.near_route([53, -1.9], [[52, -1.9], [52.01, -1.9]]), 300
        )

    def test_receipt_is_brief_and_provisional_slots_are_not_printed_as_times(self):
        view = helper.build(
            [task(str(i)) for i in range(20)],
            [event("Away", address="Venue")],
            settings=helper.defaults(),
            now=NOW,
        )
        lines = helper.receipt_brief(view)
        self.assertLessEqual(len(lines), 6)
        self.assertFalse(any("08:00" in line for line in lines))
        view["enabled"] = False
        self.assertEqual(helper.receipt_brief(view), [])

    def test_untimed_checklist_keeps_departure_and_user_written_step(self):
        events = [event("Appointment", address="Venue")]
        settings = helper.defaults()
        settings.pop("show_task_times")  # Existing saved settings also default to untimed.
        settings["tasks"] = {"Laundry": {"steps": ["Sort whites"]}}
        view = helper.build([task("Laundry")], events, travel_day(events), settings, NOW)
        self.assertIn("[ ] Laundry · Sort whites", helper.receipt_brief(view))
        self.assertIn("Leave 09:40 · Appointment", helper.receipt_brief(view))
        view["show_task_times"] = True
        self.assertIn("[ ] 08:00 Start: Laundry · Sort whites", helper.receipt_brief(view))

    def test_receipt_priority_order_expires_and_ignores_deferred_choices(self):
        tasks = [task("Laundry"), task("Job Search"), task("Tidy house")]
        settings = helper.defaults()
        settings["receipt_priorities"] = {"day": DAY, "ids": ["Tidy house", "Laundry"]}
        settings["tasks"] = {"Laundry": {"defer_until": "2026-11-03"}}
        view = helper.build(tasks, [], settings=settings, now=NOW)
        self.assertEqual([row["id"] for row in view["priorities"]], ["Tidy house", "Job Search"])
        tomorrow = helper.build(tasks, [], settings=settings, now=NOW + timedelta(days=1))
        self.assertEqual([row["id"] for row in tomorrow["priorities"]],
                         ["Job Search", "Laundry", "Tidy house"])

    def test_private_storage_validation_and_observation_prune_removed_tasks(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(helper, "FILE", Path(folder) / "helper.json"),
        ):
            helper.observe([task("one")], NOW.date())
            self.assertEqual(helper.store().read()["tasks"]["one"]["first_seen"], DAY)
            self.assertEqual(helper.FILE.stat().st_mode & 0o777, 0o600)
            helper.observe([], NOW.date())
            self.assertEqual(helper.store().read()["tasks"], {})
            with self.assertRaises(ValueError):
                helper.store().update(lambda s: s["tasks"].update(bad=dict(minutes=0)))
            self.assertEqual(helper.store().read()["tasks"], {})
            helper.FILE.write_text("{broken")
            with self.assertRaises(ValueError):
                helper.observe([task("one")])
            self.assertEqual(helper.FILE.read_text(), "{broken")


class MealResourcesTests(TestCase):
    def recipe(self, name, amount=None, cid="chicken_stock"):
        return dict(
            name=name,
            prep_components=[dict(id=cid)],
            ingredients=([amount + " Chicken stock"] if amount else []),
            equipment=["saucepan"],
            method=["Simmer"],
        )

    def test_known_amounts_sum_without_inventing_missing_quantities(self):
        components = [dict(id="chicken_stock", name="Chicken stock")]
        plan = dict(
            meals=[
                dict(kind="recipe", date=DAY, recipe=self.recipe("a", "100 ml")),
                dict(kind="recipe", date="2026-11-03", recipe=self.recipe("b")),
            ]
        )
        with patch("meals.remaining.needs_dinner", return_value=True):
            view = resources.analyse(plan, components, today=NOW.date())
            self.assertEqual(view["batches"][0]["quantities"], ["100ml chicken stock"])
            self.assertEqual(view["batches"][0]["unknown"], 1)
            view = resources.analyse(
                plan, components, {"b|chicken_stock": "0.2 l"}, NOW.date()
            )
            self.assertEqual(view["batches"][0]["quantities"], ["300ml chicken stock"])
            self.assertEqual(view["batches"][0]["unknown"], 0)

    def test_perishables_and_same_day_mayo_are_not_one_week_long_batch(self):
        for cid in ["chicken_stock", "mayonnaise"]:
            plan = dict(
                meals=[
                    dict(kind="recipe", date=d, recipe=self.recipe(d, cid=cid))
                    for d in [DAY, "2026-11-06"]
                ]
            )
            with patch("meals.remaining.needs_dinner", return_value=True):
                view = resources.analyse(
                    plan, [dict(id=cid, name=cid)], today=NOW.date()
                )
            self.assertEqual(
                [b["make_on"] for b in view["batches"]], [DAY, "2026-11-06"]
            )

    def test_reuse_score_is_bounded_and_cleanup_uses_equipment_estimate(self):
        a = self.recipe("a", cid="shawarma_spice")
        b = self.recipe("b", cid="shawarma_spice")
        self.assertGreater(
            resources.reuse_bonus(
                a, [dict(kind="recipe", date=DAY, recipe=b)], NOW.date()
            ),
            0,
        )
        raw = dict(a, ingredients=["Chicken breast"], method=["Mix"])
        cleaning = resources.cleanup(raw)
        self.assertIn("separate ready-to-eat board", cleaning["equipment"])
        self.assertIn("Clean raw-food tools", cleaning["note"])
        self.assertEqual(len(aggregate(["1 tbsp spice", "3 tsp spice"])), 1)


class HelperWebTests(TestCase):
    def setUp(self):
        from flask import Flask, session, request, abort, redirect
        from functools import wraps
        from jinja2 import ChoiceLoader, DictLoader
        from web_control import personal_helper as web

        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.patchers = [
            patch.object(helper, "FILE", root / "personal_helper.json"),
            patch.object(checklists, "FILE", root / "daily_lists.json"),
            patch("web_control.today_summary.CALENDAR", root / "calendar.json"),
            patch("services.day_travel.FILE", root / "travel.json"),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        self.app = Flask(
            __name__,
            template_folder=str(Path("web_control/templates").resolve()),
            static_folder=str(Path("web_control/static").resolve()),
        )
        self.app.secret_key = "test-only-helper-session"
        self.app.config["TESTING"] = True
        self.app.jinja_loader = ChoiceLoader(
            [DictLoader({"navigation.html": ""}), self.app.jinja_loader]
        )
        self.app.jinja_env.globals["csrf_token"] = lambda: session.get("csrf_token", "")
        for endpoint in ["index", "task_list", "day_travel", "meals_page"]:
            self.app.add_url_rule("/" + endpoint, endpoint, lambda: "ok")

        @self.app.before_request
        def csrf():
            if request.method == "POST" and request.form.get(
                "csrf_token"
            ) != session.get("csrf_token", "missing"):
                abort(403)

        @self.app.after_request
        def privacy(response):
            response.headers["Cache-Control"] = "no-store"
            return response

        def login_required(function):
            @wraps(function)
            def decorated(*a, **kw):
                if not session.get("authenticated"):
                    return redirect("/login")
                return function(*a, **kw)

            return decorated

        web.register(self.app, login_required)
        self.client = self.app.test_client()
        checklists.update("tasks", "add", title="Example <script>task</script>")
        self.identifier = checklists.load()["items"][0]["id"]

    def login(self):
        with self.client.session_transaction() as s:
            s.update(authenticated=True, csrf_token="test-csrf")

    def post(self, path, **data):
        return self.client.post(path, data=dict(csrf_token="test-csrf", **data))

    def test_auth_csrf_escaping_and_get_does_not_write(self):
        self.assertEqual(self.client.get("/helper").status_code, 302)
        self.login()
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No provider requests on GET"),
        ):
            response = self.client.get("/helper")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"&lt;script&gt;task&lt;/script&gt;", response.data)
        self.assertFalse(helper.FILE.exists())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            self.client.post(
                "/helper/task", data={"task": self.identifier}
            ).status_code,
            403,
        )

    def test_task_edits_steps_defer_and_complete_share_main_checklist(self):
        self.login()
        self.post(
            "/helper/task",
            task=self.identifier,
            minutes="15",
            context="home",
            effort="low",
            steps="Find notebook\nWrite questions",
        )
        self.post("/helper/task-action", task=self.identifier, action="step", index="0")
        self.assertEqual(
            helper.store().read()["tasks"][self.identifier]["step_done"], [0]
        )
        from receipt.local_time import uk_today

        tomorrow = (uk_today() + timedelta(days=1)).isoformat()
        self.post(
            "/helper/task-action", task=self.identifier, action="defer", until=tomorrow
        )
        self.assertEqual(
            helper.store().read()["tasks"][self.identifier]["defer_until"], tomorrow
        )
        self.post(
            "/helper/task",
            task=self.identifier,
            minutes="15",
            context="home",
            effort="low",
            steps="Find notebook\nWrite questions",
        )
        self.assertEqual(
            helper.store().read()["tasks"][self.identifier]["defer_until"], ""
        )
        self.post("/helper/task-action", task=self.identifier, action="complete")
        self.assertTrue(checklists.is_done(checklists.load()["items"][0]))
        self.post("/helper/task-action", task=self.identifier, action="complete")
        self.assertTrue(checklists.is_done(checklists.load()["items"][0]))

    def test_receipt_order_can_be_saved_and_reset_in_the_helper(self):
        from receipt.local_time import uk_today

        self.login()
        day = uk_today().isoformat()
        checklists.update("tasks", "add", title="Laundry")
        laundry = checklists.load()["items"][-1]["id"]
        order = [laundry, self.identifier]
        self.post("/helper/receipt-priorities", day=day, priority=order)
        self.assertEqual([row["id"] for row in helper.context()["priorities"]], order)
        self.post("/helper/receipt-priorities", day=day, priority=[laundry, laundry])
        self.assertEqual(helper.store().read()["receipt_priorities"]["ids"], order)
        self.post("/helper/receipt-priorities", action="reset")
        self.assertNotIn("receipt_priorities", helper.store().read())

    def test_quick_move_hides_task_from_the_full_receipt_until_weekend(self):
        from datetime import date

        self.login()
        monday = date(2026, 11, 2)
        with patch("web_control.personal_helper.uk_today", return_value=monday):
            self.post("/helper/task-action", task=self.identifier, action="tomorrow")
            self.assertEqual(helper.store().read()["tasks"][self.identifier]["defer_until"], "2026-11-03")
            self.post("/helper/task-action", task=self.identifier, action="weekend")
        self.assertEqual(helper.store().read()["tasks"][self.identifier]["defer_until"], "2026-11-07")
        with patch.object(checklists, "today", return_value=monday.isoformat()):
            self.assertEqual(checklists.task_text(""), "")
        with patch.object(checklists, "today", return_value="2026-11-07"):
            self.assertIn("Example", checklists.task_text(""))

    def test_rules_and_errands_validate_without_overwriting_good_state(self):
        self.login()
        self.post(
            "/helper/rule",
            match="Therapy",
            lead_hours="12",
            take="Notebook",
            prepare="Questions",
        )
        self.assertEqual(len(helper.store().read()["rules"]), 1)
        self.post(
            "/helper/rule",
            match="Therapy",
            lead_hours="999",
            take="Notebook",
            prepare="Questions",
        )
        self.assertEqual(len(helper.store().read()["rules"]), 1)
        self.post(
            "/helper/errand",
            task=self.identifier,
            address="Example pharmacy",
            hours="Check hours",
        )
        self.assertIsNone(helper.store().read()["errands"][self.identifier]["point"])
        self.assertEqual(
            helper.store().read()["tasks"][self.identifier]["context"], "outside"
        )
        self.assertEqual(
            self.post(
                "/helper/errand", task="nonexistent", address="Ignored"
            ).status_code,
            404,
        )

    def test_recipe_amount_override_is_positive_and_scoped_to_known_component(self):
        self.login()
        from meals import legacy_planner as planner

        recipe = dict(name="Example meal", prep_components=[dict(id="chicken_stock")])
        with (
            patch.object(planner, "recipes", return_value=[recipe]),
            patch.object(
                planner,
                "_load",
                return_value={
                    "components": [dict(id="chicken_stock", name="Chicken stock")]
                },
            ),
        ):
            self.post(
                "/helper/meal-quantity",
                recipe="Example meal",
                component="chicken_stock",
                quantity="2 tbsp",
            )
            self.assertEqual(
                helper.store().read()["meal_uses"]["Example meal|chicken_stock"],
                "2 tbsp",
            )
            self.post(
                "/helper/meal-quantity",
                recipe="Example meal",
                component="chicken_stock",
                quantity="2 tbsp arbitrary text",
            )
            self.assertEqual(
                helper.store().read()["meal_uses"]["Example meal|chicken_stock"],
                "2 tbsp",
            )
            self.assertEqual(
                self.post(
                    "/helper/meal-quantity",
                    recipe="Other meal",
                    component="chicken_stock",
                    quantity="2 tbsp",
                ).status_code,
                400,
            )
            self.post(
                "/helper/meal-quantity",
                recipe="Example meal",
                component="chicken_stock",
                quantity="",
            )
            self.assertEqual(helper.store().read()["meal_uses"], {})
