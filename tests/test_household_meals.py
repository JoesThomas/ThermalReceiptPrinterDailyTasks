"""Household constraints, quantities, sourced references and calendar-aware breakfasts."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from fractions import Fraction
from unittest import TestCase
from unittest.mock import patch
from meals import (
    household as h,
    breakfast as b,
    nutrition_guidance as g,
    emergency_food as reserve,
    legacy_planner as planner,
    monthly,
)
from receipt.local_time import UK
from storage import write_json
from test_monthly_meals import MonthlyFixture, recipe

SAT = date(2026, 11, 7)


def settings(**changes):
    s = h.defaults()
    s.update(configured=True, **changes)
    return s


def calendar(events=(), plan=None, verified=True):
    return dict(events=list(events), plan=plan or {}, verified=verified)


def event(a="07:00", z="10:00", location=""):
    return dict(
        title="Morning appointment",
        date=SAT.isoformat(),
        start_dt=f"{SAT}T{a}:00+00:00",
        end_dt=f"{SAT}T{z}:00+00:00" if z else None,
        location=location,
    )


class HouseholdFixture(MonthlyFixture):
    def setUp(self):
        super().setUp()
        self.hp = patch.object(h, "FILE", self.root / "household.json")
        self.hp.start()
        self.addCleanup(self.hp.stop)


class HouseholdTests(HouseholdFixture, TestCase):
    def test_combined_allergens_diets_and_dislikes_filter_the_actual_pool(self):
        s = settings()
        vegan = dict(
            h.person(),
            name="Second",
            diet="vegan",
            allergens=["milk"],
            avoid=["carrot"],
        )
        s["people"].append(vegan)
        chicken = recipe("Chicken", ["150g chicken breast"])
        plant = dict(
            recipe("Beans", ["150g beans", "1 carrot"]),
            dietary={"vegan": True, "vegetarian": True},
        )
        self.assertFalse(h.permitted(chicken, s, SAT))
        self.assertFalse(h.permitted(plant, s, SAT))
        plant["ingredients"] = ["150g beans", "75g rice"]
        self.assertTrue(h.permitted(plant, s, SAT))
        plant["ingredients"] = ["150g beans", "100ml milk"]
        self.assertFalse(h.permitted(plant, s, SAT))
        h.store().update(lambda v: v.update(s))
        self.assertFalse(planner._eligible(chicken, SAT, planner.preferences()))

    def test_pescatarian_allows_fish_but_excludes_meat_and_meat_stock(self):
        s = settings()
        s["people"][0]["diet"] = "pescatarian"
        r = dict(
            recipe("Fish bowl", ["100g salmon", "75g rice"]),
            dietary={"contains_meat": False, "contains_fish_or_shellfish": True},
        )
        self.assertTrue(h.permitted(r, s, SAT))
        self.assertIn("fish", {v["id"] for v in reserve.report(SAT, s)["options"]})
        r["ingredients"].append("100ml chicken stock")
        self.assertFalse(h.permitted(r, s, SAT))
        r["ingredients"].pop()
        s["people"].append(dict(h.person(), diet="vegetarian"))
        self.assertFalse(h.permitted(r, s, SAT))

    def test_coeliac_filter_combines_with_diet_and_replaces_standard_lunch_wrap(self):
        s = settings()
        s["people"][0].update(diet="pescatarian", coeliac=True)
        r = dict(
            recipe("Fish bowl", ["100g salmon", "75g rice"]),
            dietary={"contains_meat": False, "contains_fish_or_shellfish": True},
        )
        self.assertTrue(h.permitted(r, s, SAT))
        self.assertEqual(
            h.prepare(r, SAT, s)["lunch"]["extra_ingredients"],
            ["1 gluten-free tortilla"],
        )
        self.assertEqual(r["lunch"]["extra_ingredients"], ["1 tortilla"])
        for ingredient in ("1 tbsp soy sauce", "1 tsp barley malt", "40g spelt"):
            with self.subTest(ingredient=ingredient):
                self.assertFalse(h.permitted(dict(r, ingredients=[ingredient]), s, SAT))
        r["lunch"]["extra_ingredients"] = ["1 pitta"]
        self.assertFalse(h.permitted(r, s, SAT))

    def test_coeliac_breakfast_filters_standard_oats_and_respects_avoid(self):
        s = settings()
        s["people"][0]["coeliac"] = True
        choices = {r["name"]: r for r in b.catalogue(SAT, s)}
        self.assertFalse(
            h.permitted(choices["Quick porridge & fruit"], s, SAT, "breakfast")
        )
        certified = choices["Gluten-free porridge & fruit"]
        self.assertTrue(h.permitted(certified, s, SAT, "breakfast"))
        s["people"][0]["avoid"] = ["oats"]
        self.assertFalse(h.permitted(certified, s, SAT, "breakfast"))

    def test_dairy_alternatives_and_certified_gluten_free_foods_are_not_false_milk_gluten(
        self,
    ):
        s = settings()
        s["people"][0].update(
            diet="vegan", allergens=["milk", "cereals_containing_gluten"]
        )
        r = next(
            r for r in b.catalogue(SAT, s) if r["name"] == "Soya yoghurt, oats & fruit"
        )
        self.assertTrue(h.permitted(r, s, SAT, "breakfast"))
        r["ingredients"] = ["45g oats", "200ml milk"]
        self.assertFalse(h.permitted(r, s, SAT, "breakfast"))

    def test_scaled_dinner_reserves_planned_lunch_and_is_idempotent(self):
        s = settings()
        s["people"].append(dict(h.person(), name="Two"))
        r = recipe("Rice", ["100g rice"])
        r.update(cook_servings=1, meal_type="single")
        r["lunch"]["extra_dinner_portion"] = 0.5
        out = h.prepare(r, SAT, s)
        self.assertEqual(out["ingredients"], ["300g rice"])
        self.assertEqual(out["_household_cook"], 3)
        self.assertEqual(out["lunch"]["extra_ingredients"], ["2 tortilla"])
        self.assertEqual(h.prepare(out, SAT, s), out)
        self.assertEqual(r["ingredients"], ["100g rice"])

    def test_buying_tomorrows_lunch_removes_extra_cooking(self):
        s = settings()
        r = recipe("Rice", ["100g rice"])
        r["lunch"]["extra_dinner_portion"] = 0.5
        write_json(
            planner.OVERRIDES_FILE, {"2026-11-08": {"lunch": {"type": "buy_lunch"}}}
        )
        out = h.prepare(r, SAT, s)
        self.assertEqual(out["ingredients"], ["100g rice"])
        self.assertEqual(out["lunch"], {})
        self.assertFalse(out["_household_lunch_reserved"])

    def test_custom_edits_and_removals_invalidate_saved_snapshots(self):
        r = dict(recipe("Custom", ["100g lentils"]), id="a" * 24, slot="dinner")
        s = settings(custom=[deepcopy(r)])
        self.assertTrue(h.permitted(r, s, SAT))
        scaled = h.prepare(r, SAT, s)
        self.assertTrue(h.permitted(scaled, s, SAT))
        s["custom"][0]["ingredients"] = ["100g eggs"]
        self.assertFalse(h.permitted(r, s, SAT))
        self.assertFalse(h.permitted(scaled, s, SAT))
        s["custom"] = []
        self.assertFalse(h.permitted(r, s, SAT))

    def test_monthly_shopping_includes_scaled_breakfasts_until_recorded_eaten(self):
        s = settings(breakfasts=["Wholegrain cereal & fruit"])
        s["people"].append(dict(h.person(), name="Two"))
        h.store().update(lambda v: v.update(s))
        view = monthly.report("2026-11", SAT)

        def amount(report):
            return [
                a
                for visit in report["visits"]
                for item in visit["items"]
                if "cereal" in item["key"]
                for a in item["amounts"]
            ]

        before = amount(view)
        self.assertTrue(before)
        h.store().update(lambda v: v["breakfast_done"].append(SAT.isoformat()))
        after = amount(monthly.report("2026-11", SAT))
        self.assertNotEqual(before, after)

    def test_batch_yield_and_unmeasured_ingredients_are_not_guessed(self):
        s = settings()
        s["people"] = [dict(h.person(), name=str(i)) for i in range(3)]
        r = recipe("Batch", ["400g rice", "herbs to taste"])
        r.update(cook_servings=4, meal_type="batch")
        r["lunch"]["source"] = "batch_portion"
        out = h.prepare(r, SAT, s)
        self.assertEqual(out["_household_cook"], 6)
        self.assertEqual(out["ingredients"][0], "600g rice")
        self.assertIn("unmeasured", out["ingredients"][1])
        self.assertEqual(h.scaled_line("1 tbsp oil", Fraction(2)), "2 tbsp oil")

    def test_under_twos_are_not_given_shared_adult_menus_or_energy_targets(self):
        s = settings()
        s["people"][0]["birth_year"] = 2025
        self.assertEqual(h.shared(s, SAT), [])
        self.assertIsNone(b.plan(SAT, s, calendar()))
        self.assertIsNone(g.energy(s["people"][0], SAT)["low"])
        self.assertTrue(reserve.report(SAT, s)["infant"])
        self.assertEqual(reserve.report(SAT, s)["options"], [])

    def test_whole_nuts_are_excluded_for_possible_under_fives(self):
        s = settings()
        s["people"][0]["birth_year"] = 2023
        ids = {r["id"] for r in reserve.report(SAT, s)["options"]}
        self.assertNotIn("nuts", ids)
        recipe_with_nuts = dict(
            recipe("Nut cereal", ["whole nuts"]),
            dietary={"vegetarian": True, "vegan": True},
        )
        self.assertFalse(h.permitted(recipe_with_nuts, s, SAT))

    def test_age_ranges_roll_forward_by_birth_year_without_personal_targets(self):
        p = dict(h.person(), birth_year=1961, reference="male")
        ref = g.energy(p, SAT)
        self.assertEqual(ref["ages"], (64, 65))
        self.assertEqual((ref["low"], ref["high"]), (2342, 2581))
        next_year = g.energy(p, date(2027, 1, 1))
        self.assertEqual(next_year["ages"], (65, 66))
        self.assertEqual(next_year["low"], 2342)
        p["clinical"] = True
        self.assertIsNone(g.energy(p, SAT)["low"])
        self.assertIn("population", ref["note"])

    def test_sourced_child_and_adult_values_are_not_interchanged(self):
        self.assertEqual(g.CHILD_M[17], 3155)
        self.assertEqual(g.CHILD_F[17], 2462)
        r = g.energy(dict(h.person(), birth_year=2008, reference="male"), SAT)
        self.assertEqual((r["low"], r["high"]), (3083, 3155))
        r = g.energy(dict(h.person(), birth_year=1996, reference="range"), SAT)
        self.assertEqual((r["low"], r["high"]), (2175, 2749))

    def test_seasonal_scoring_uses_meal_date_and_leaves_preserved_food_neutral(self):
        s = settings(balanced=False)
        carrot = recipe("Carrot", ["100g carrots"])
        berries = recipe("Berry", ["100g strawberries"])
        self.assertGreater(g.score(carrot, [], SAT, s), g.score(berries, [], SAT, s))
        self.assertGreater(
            g.score(berries, [], date(2026, 7, 1), s),
            g.score(carrot, [], date(2026, 7, 1), s),
        )
        self.assertEqual(
            g.produce(recipe("Frozen", ["100g frozen strawberries"])), set()
        )
        s["seasonal"] = False
        self.assertEqual(g.score(carrot, [], SAT, s), 0)

    def test_reserve_suggestions_use_household_filters_and_water_is_explicit_stock(
        self,
    ):
        s = settings(reserve_days=3, water_litres=3, water_have=5)
        s["people"].append(
            dict(h.person(), name="Two", diet="vegan", allergens=["soybeans"])
        )
        result = reserve.report(SAT, s)
        self.assertEqual(result["water"], 18)
        self.assertEqual(result["water_missing"], 13)
        self.assertFalse(
            {"fish", "meat", "milk", "soya"} & {v["id"] for v in result["options"]}
        )
        s["reserve_targets"]["beans"] = 6
        s["reserve_have"]["beans"] = 2
        row = next(r for r in reserve.report(SAT, s)["options"] if r["id"] == "beans")
        self.assertEqual(row["missing"], 4)
        self.assertIsNone(
            next(r for r in result["options"] if r["id"] == "fruit")["target"]
        )

    def test_incompatible_saved_future_meals_are_replaced_not_returned_as_safe(self):
        s = settings()
        s["people"][0].update(diet="vegan")
        h.store().update(lambda v: v.update(s))
        chicken = recipe("Chicken", ["100g chicken"])
        plant = dict(
            recipe("Beans", ["100g beans", "75g rice"]),
            dietary={"vegan": True, "vegetarian": True},
        )
        write_json(planner.RECIPES_FILE, {"recipes": [chicken, plant]})
        self.save(SAT, [dict(date=SAT.isoformat(), kind="recipe", recipe=chicken)])
        monthly.generate("2026-11", SAT)
        actual = planner.load_plan_for(SAT, raw=True)
        self.assertEqual(
            next(m for m in actual["meals"] if m["date"] == SAT.isoformat())["recipe"][
                "name"
            ],
            "Beans",
        )

    def test_settings_corruption_does_not_reset_dietary_data(self):
        h.FILE.write_text("{broken")
        with self.assertRaises(ValueError):
            h.store().update(lambda v: v.update(configured=True))
        self.assertEqual(h.FILE.read_text(), "{broken")


class BreakfastTests(HouseholdFixture, TestCase):
    def test_breakfast_choices_do_not_use_dinner_favourites_and_custom_breakfast_works(
        self,
    ):
        custom = b.recipe(
            "Quick custom breakfast", 3, ["100g tinned peaches"], ["Serve"], vegan=True
        )
        custom["id"] = "b" * 24
        s = settings(dinners=["Chicken"], breakfasts=[custom["name"]], custom=[custom])
        h.store().update(lambda v: v.update(s))
        result = b.plan(SAT, s, calendar())
        self.assertFalse(result["unavailable"])
        self.assertEqual(result["recipe"]["name"], custom["name"])
        self.assertNotIn("birth_year", " ".join(b.receipt_lines(SAT)))

    def test_weekday_uses_quick_options_even_with_a_clear_calendar(self):
        result = b.plan(date(2026, 11, 9), settings(), calendar())
        self.assertLessEqual(result["recipe"]["total_minutes"], 5)

    def test_weekend_allows_leisurely_choices_only_with_time(self):
        result = b.plan(SAT, settings(), calendar())
        self.assertGreater(result["recipe"]["total_minutes"], 5)
        result = b.plan(SAT, settings(), calendar([event()]))
        self.assertLessEqual(result["recipe"]["total_minutes"], 5)
        self.assertIsNone(result["start"])

    def test_unverified_future_calendar_falls_back_without_inventing_a_free_day(self):
        result = b.plan(SAT, settings(), calendar(verified=False))
        self.assertLessEqual(result["recipe"]["total_minutes"], 5)
        self.assertIsNone(result["start"])
        s = settings(provisional_weekends=True)
        self.assertGreater(
            b.plan(SAT, s, calendar(verified=False))["recipe"]["total_minutes"], 5
        )

    def test_morning_departure_and_unknown_end_block_cooking_time(self):
        trip = {
            "legs": [
                dict(
                    depart="2026-11-07T07:10:00+00:00",
                    arrive="2026-11-07T10:00:00+00:00",
                )
            ]
        }
        result = b.plan(
            SAT, settings(), calendar([event("08:00", "09:00", "Venue")], trip)
        )
        self.assertLessEqual(result["recipe"]["total_minutes"], 5)
        unknown = b.plan(SAT, settings(), calendar([event("07:00", None)]))
        self.assertIsNone(unknown["start"])

    def test_empty_or_conflicting_selection_is_explicit_not_a_dietary_bypass(self):
        s = settings(breakfasts=["Scrambled eggs & toast"])
        s["people"][0]["allergens"] = ["eggs"]
        result = b.plan(SAT, s, calendar())
        self.assertTrue(result["unavailable"])
        self.assertIn("No enabled breakfast", result["note"])

    def test_choice_is_deterministic_and_done_breakfast_is_not_shopped_again(self):
        s = settings()
        h.store().update(lambda v: v.update(s))
        self.assertEqual(
            b.plan(SAT, s, calendar())["recipe"], b.plan(SAT, s, calendar())["recipe"]
        )
        s["breakfast_done"] = [SAT.isoformat()]
        result = b.plan(SAT, s, calendar())
        self.assertTrue(result["done"])
        s["breakfast_enabled"] = False
        self.assertIsNone(b.plan(SAT, s, calendar()))

    def test_newer_calendar_overrides_an_older_saved_travel_snapshot(self):
        now = datetime(2026, 11, 7, 6, tzinfo=UK)
        state = dict(
            checked_at=now.isoformat(),
            coverage_from="2026-11-07",
            coverage_to="2026-11-14",
            status="checked",
            warnings=[],
            events=[event()],
        )
        saved = dict(
            checked=(now - timedelta(hours=1)).isoformat(),
            events=[],
            plan=dict(
                day="2026-11-07",
                checked=(now - timedelta(hours=1)).isoformat(),
                legs=[],
            ),
        )
        result = b.context(SAT, now, (state, {"days": {SAT.isoformat(): saved}}))
        self.assertEqual(result["events"], [event()])
        self.assertEqual(result["plan"], {})
        self.assertLessEqual(
            b.plan(SAT, settings(), result)["recipe"]["total_minutes"], 5
        )

    def test_snapshot_coverage_and_age_are_required(self):
        now = datetime(2026, 11, 7, 6, tzinfo=UK)
        state = dict(
            checked_at=now.isoformat(), status="checked", warnings=[], events=[]
        )
        self.assertFalse(b.context(SAT, now, (state, {"days": {}}))["verified"])
        state.update(coverage_from="2026-11-07", coverage_to="2026-11-08")
        self.assertTrue(b.context(SAT, now, (state, {"days": {}}))["verified"])
        self.assertFalse(
            b.context(date(2026, 11, 9), now, (state, {"days": {}}))["verified"]
        )
        state["checked_at"] = (now - timedelta(days=2)).isoformat()
        self.assertFalse(b.context(SAT, now, (state, {"days": {}}))["verified"])


class MealSettingsWebTests(HouseholdFixture, TestCase):
    def setUp(self):
        super().setUp()
        from flask import Flask, session, request, abort, redirect
        from functools import wraps
        from jinja2 import ChoiceLoader, DictLoader
        from web_control.meal_settings import register

        clock = patch("web_control.meal_settings.uk_today", return_value=SAT)
        clock.start()
        self.addCleanup(clock.stop)
        self.app = Flask(
            __name__,
            template_folder=str(Path("web_control/templates").resolve()),
            static_folder=str(Path("web_control/static").resolve()),
        )
        self.app.secret_key = "test-only-household"
        self.app.config["TESTING"] = True
        self.app.jinja_loader = ChoiceLoader(
            [DictLoader({"navigation.html": ""}), self.app.jinja_loader]
        )
        self.app.jinja_env.globals["csrf_token"] = lambda: session.get("csrf_token", "")
        for path, name in [
            ("/meals", "meals_page"),
            ("/meals/month", "monthly_meals_page"),
        ]:
            self.app.add_url_rule(path, name, lambda: "ok")

        @self.app.before_request
        def csrf():
            if request.method == "POST" and request.form.get(
                "csrf_token"
            ) != session.get("csrf_token", "missing"):
                abort(403)

        def auth(fn):
            @wraps(fn)
            def run(*a, **kw):
                return (
                    fn(*a, **kw) if session.get("authenticated") else redirect("/login")
                )

            return run

        register(self.app, auth)
        self.client = self.app.test_client()

    def login(self):
        with self.client.session_transaction() as s:
            s.update(authenticated=True, csrf_token="csrf")

    def post(self, path, **data):
        return self.client.post(path, data=dict(csrf_token="csrf", **data))

    def form(self):
        return dict(
            person_index=["0", "1"],
            person_name_0="Adult",
            birth_year_0="1996",
            reference_0="male",
            diet_0="omnivore",
            portion_0="1",
            person_name_1="Child",
            birth_year_1="2020",
            reference_1="range",
            diet_1="vegetarian",
            portion_1=".5",
            allergen_1=["milk"],
            all_dinners="on",
            all_breakfasts="on",
            balanced="on",
            seasonal="on",
            breakfast_enabled="on",
        )

    def test_auth_csrf_and_read_only_settings(self):
        self.assertEqual(self.client.get("/meals/settings").status_code, 302)
        self.login()
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No network"),
        ):
            response = self.client.get("/meals/settings")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(h.FILE.exists())
        self.assertIn(b"SACN population estimates", response.data)
        self.assertEqual(
            self.client.post("/meals/settings/household", data=self.form()).status_code,
            403,
        )

    def test_people_and_choices_save_and_change_recipe_filtering(self):
        self.login()
        form = self.form()
        form.update(diet_0="pescatarian", coeliac_0="on")
        self.post("/meals/settings/household", **form)
        s = h.store().read()
        self.assertEqual(s["people"][0]["diet"], "pescatarian")
        self.assertTrue(s["people"][0]["coeliac"])
        self.assertEqual(len(s["people"]), 2)
        self.assertEqual(s["people"][1]["allergens"], ["milk"])
        self.assertFalse(
            planner._eligible(
                recipe("Chicken", ["100g chicken"]), SAT, planner.preferences()
            )
        )
        self.assertEqual(s["people"][1]["portion"], 0.5)
        self.assertTrue(s["seasonal"])

    def test_custom_recipe_and_reserve_forms_are_real_and_validated(self):
        self.login()
        self.post(
            "/meals/settings/recipe",
            name="Family lentils",
            slot="dinner",
            minutes="20",
            servings="2",
            ingredients="200g lentils\n150g rice",
            method="Cook as directed",
            vegan="on",
            calories="500",
        )
        s = h.store().read()
        self.assertEqual(s["custom"][0]["cook_servings"], 2)
        self.assertTrue(any(r["name"] == "Family lentils" for r in planner.recipes()))
        self.post(
            "/meals/settings/reserve",
            reserve_days="5",
            water_litres="3",
            water_have="2",
            target_beans="6",
            have_beans="2",
            reserve_notes="Rotate stocks",
        )
        self.assertEqual(reserve.report(SAT)["water_missing"], 13)
        before = h.FILE.read_bytes()
        self.post(
            "/meals/settings/reserve",
            reserve_days="0",
            water_litres="nan",
            water_have="-1",
        )
        self.assertEqual(h.FILE.read_bytes(), before)

    def test_breakfast_override_rejects_allergens_and_eaten_is_idempotent(self):
        self.login()
        s = settings()
        s["people"][0]["allergens"] = ["eggs"]
        h.store().update(lambda v: v.update(s))
        self.post(
            "/meals/breakfast", day=SAT.isoformat(), breakfast="Scrambled eggs & toast"
        )
        self.assertNotIn(SAT.isoformat(), h.store().read()["breakfast_overrides"])
        self.post(
            "/meals/breakfast",
            day=SAT.isoformat(),
            breakfast="Gluten-free porridge & fruit",
        )
        self.assertEqual(
            h.store().read()["breakfast_overrides"][SAT.isoformat()],
            "Gluten-free porridge & fruit",
        )
        self.post("/meals/breakfast", day=SAT.isoformat(), action="eaten")
        self.post("/meals/breakfast", day=SAT.isoformat(), action="eaten")
        self.assertEqual(h.store().read()["breakfast_done"], [SAT.isoformat()])
        self.post("/meals/breakfast", day=SAT.isoformat(), action="undo")
        self.assertEqual(h.store().read()["breakfast_done"], [])

    def test_recipe_text_is_escaped_and_invalid_profile_never_overwrites(self):
        self.login()
        s = settings()
        s["people"][0]["name"] = "<script>name</script>"
        h.store().update(lambda v: v.update(s))
        response = self.client.get("/meals/settings")
        self.assertIn(b"&lt;script&gt;name&lt;/script&gt;", response.data)
        self.assertNotIn(b"<script>name</script>", response.data)
        before = h.FILE.read_bytes()
        form = self.form()
        form["birth_year_0"] = "3000"
        self.post("/meals/settings/household", **form)
        self.assertEqual(h.FILE.read_bytes(), before)
