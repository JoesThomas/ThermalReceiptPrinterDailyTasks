"""Monthly menus share weekly files; specialist shopping remains dated and measurable."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from meals import monthly, legacy_planner as planner
from receipt import lifestyle
from storage import write_json

TODAY = date(2026, 11, 6)


def recipe(name="Chicken", ingredients=None):
    return dict(
        name=name,
        total_minutes=20,
        ingredients=ingredients or ["150g chicken breast", "75g rice", "1 carrot"],
        allergens={"uk_14": []},
        dietary={"vegetarian": False},
        method=["Cook"],
        prep_components=[],
        cost={"estimated_per_portion": 4},
        lunch={"extra_ingredients": ["1 tortilla"]},
    )


class MonthlyFixture:
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        from actions import checklists, personal_helper
        from meals import household

        self.patchers = [
            patch.object(monthly, "FILE", self.root / "settings.json"),
            patch.object(household, "FILE", self.root / "household.json"),
            patch.object(checklists, "FILE", self.root / "tasks.json"),
            patch.object(planner, "PLANS_DIR", self.root / "plans"),
            patch.object(planner, "PANTRY_FILE", self.root / "pantry.json"),
            patch.object(planner, "RECIPES_FILE", self.root / "recipes.json"),
            patch.object(planner, "PREFERENCES_FILE", self.root / "prefs.json"),
            patch.object(planner, "HISTORY_FILE", self.root / "history.json"),
            patch.object(planner, "OVERRIDES_FILE", self.root / "overrides.json"),
            patch.object(planner, "COMPONENTS_FILE", self.root / "components.json"),
            patch.object(personal_helper, "FILE", self.root / "helper.json"),
            patch.object(lifestyle, "FILE", self.root / "lifestyle.json"),
            patch("receipt.local_time.uk_today", return_value=TODAY),
            patch.object(monthly, "uk_today", return_value=TODAY),
            patch("web_control.live_data.meal_confirmation", return_value=None),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        write_json(
            planner.RECIPES_FILE,
            {"recipes": [recipe("Chicken " + str(i)) for i in range(12)]},
        )
        write_json(planner.PREFERENCES_FILE, dict(weekday_max_minutes=30))

    def save(self, day, rows):
        write_json(
            planner.plan_path(planner.current_week_sunday(day)), dict(meals=rows)
        )


class MonthlyTests(MonthlyFixture, TestCase):
    def test_calendar_months_and_leap_february_cover_each_day_once(self):
        self.assertEqual(monthly.bounds("2028-02")[1], date(2028, 2, 29))
        first, last = monthly.bounds("2026-11")
        self.assertEqual(len(list(monthly.week_starts(first, last))), 5)
        view = monthly.report("2026-11", TODAY)
        self.assertEqual(len(view["days"]), 30)
        self.assertEqual(len(view["missing"]), 25)
        self.assertFalse(planner.PLANS_DIR.exists())
        with self.assertRaises(ValueError):
            monthly.bounds("2026-13")

    def test_generation_preserves_existing_meals_fills_gaps_and_is_idempotent(self):
        special = dict(
            date="2026-11-07", kind="eat_out", name="Booked dinner", estimated_cost=20
        )
        self.save(TODAY, [special])
        self.assertGreater(monthly.generate("2026-11", TODAY), 0)
        view = monthly.report("2026-11", TODAY)
        self.assertEqual(view["missing"], [])
        self.assertEqual(
            planner.load_plan_for(date(2026, 11, 7), raw=True)["meals"][-1], special
        )
        self.assertFalse(any(row["meal"] for row in view["days"] if row["day"] < TODAY))
        before = {p: p.read_bytes() for p in planner.PLANS_DIR.glob("*.json")}
        self.assertEqual(monthly.generate("2026-11", TODAY), 0)
        self.assertTrue(all(p.read_bytes() == body for p, body in before.items()))
        self.assertEqual(monthly.store().read()["active_month"], "2026-11")
        self.assertEqual(monthly.FILE.stat().st_mode & 0o777, 0o600)

    def test_corrupt_saved_week_is_not_overwritten_or_partially_regenerated(self):
        path = planner.plan_path(date(2026, 11, 15))
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        with self.assertRaises(ValueError):
            monthly.generate("2026-11", TODAY)
        self.assertEqual(path.read_text(), "{broken")
        self.assertEqual(list(planner.PLANS_DIR.glob("*.json")), [path])

    def test_monthly_changes_feed_the_actual_weekly_plan_and_reject_past_days(self):
        monthly.generate("2026-11", TODAY)
        monthly.change_meal("2026-11", "2026-11-10", "Chicken 8", TODAY)
        actual = planner.load_plan_for(date(2026, 11, 10), raw=True)
        self.assertEqual(
            next(
                m["recipe"]["name"]
                for m in actual["meals"]
                if m["date"] == "2026-11-10"
            ),
            "Chicken 8",
        )
        with self.assertRaises(ValueError):
            monthly.change_meal("2026-11", "2026-11-05", "Chicken 8", TODAY)
        write_json(planner.PREFERENCES_FILE, dict(vegetarian_only=True))
        with self.assertRaises(ValueError):
            monthly.change_meal("2026-11", "2026-11-11", "Chicken 8", TODAY)

    def test_classification_protects_fresh_food_and_handles_preserved_names(self):
        for line, category in [
            ("150g chicken breast", "Meat"),
            ("1 tin tuna", "Store cupboard / frozen"),
            ("150g salmon", "Fish"),
            ("80g frozen peas", "Store cupboard / frozen"),
            ("fresh herbs", "Fresh produce"),
            ("1 tsp black pepper", "Store cupboard / frozen"),
            ("1 tsp garlic granules", "Store cupboard / frozen"),
            ("200ml chicken stock", "Fresh essentials"),
            ("1 chicken stock cube", "Store cupboard / frozen"),
            ("Greek yoghurt", "Fresh essentials"),
            ("unknown product", "Fresh essentials"),
        ]:
            self.assertEqual(monthly.category(line), category, line)

    def test_main_shop_combines_month_quantities_but_meat_is_weekly(self):
        s = monthly.defaults()
        rows = []
        for day in [date(2026, 11, 8), date(2026, 11, 15)]:
            rows.extend(
                [
                    dict(day=day, line="0.5kg rice", recipe="Dinner"),
                    dict(day=day, line="150g chicken breast", recipe="Dinner"),
                ]
            )
        view = monthly.shopping(rows, s, date(2026, 11, 1), TODAY)
        main = [v for v in view["visits"] if v["shop"] == "Main supermarket shop"]
        self.assertEqual(len(main), 1)
        self.assertEqual(main[0]["items"][0]["amounts"], ["1000g rice"])
        self.assertEqual(
            [v["day"] for v in view["visits"] if v["shop"] == "Butcher"],
            [date(2026, 11, 7), date(2026, 11, 14)],
        )
        self.assertTrue(
            all(
                v["day"] <= date.fromisoformat(i["needs"][0])
                for v in view["visits"]
                for i in v["items"]
            )
        )

    def test_midweek_veg_and_local_shop_can_avoid_supermarket_topups(self):
        s = monthly.defaults()
        s.update(veg_topup=True, veg_day=2)
        s["shops"]["Fresh essentials"] = "Greengrocer"
        rows = [
            dict(day=date(2026, 11, 12), line="1 carrot", recipe="Dinner"),
            dict(day=date(2026, 11, 12), line="2 eggs", recipe="Dinner"),
        ]
        view = monthly.shopping(rows, s, date(2026, 11, 1), TODAY)
        self.assertEqual(view["supermarket_stops"], 0)
        self.assertIn(date(2026, 11, 11), [v["day"] for v in view["visits"]])
        s["overrides"]["carrot"] = "Fresh essentials"
        combined = monthly.shopping(rows, s, date(2026, 11, 1), TODAY)
        self.assertEqual(combined["stops"], 1)
        self.assertEqual(len(combined["visits"][0]["items"]), 2)

    def test_pantry_is_not_assumed_to_cover_the_month_and_unknown_amounts_stay_visible(
        self,
    ):
        write_json(planner.PANTRY_FILE, {"items": {"rice": True}})
        view = monthly.shopping(
            [
                dict(day=TODAY, line="500g rice", recipe="Dinner"),
                dict(day=TODAY, line="fresh herbs", recipe="Dinner"),
            ],
            monthly.defaults(),
            TODAY,
            TODAY,
        )
        items = [i for v in view["visits"] for i in v["items"]]
        self.assertTrue(next(i for i in items if i["key"] == "rice")["pantry"])
        self.assertTrue(
            next(i for i in items if i["key"] == "fresh herbs")["unmeasured"]
        )

    def test_eaten_away_and_skipped_meals_do_not_create_extra_leftover_purchases(self):
        meals = [
            dict(date="2026-11-06", kind="recipe", recipe=recipe()),
            dict(date="2026-11-07", kind="skipped", name="Skipped"),
            dict(date="2026-11-08", kind="recipe", recipe=recipe()),
        ]
        with patch(
            "meals.remaining.needs_dinner",
            side_effect=lambda m, on: (
                m.get("kind") == "recipe" and m["date"] == "2026-11-08"
            ),
        ):
            rows = monthly.requirements(meals, TODAY)
        self.assertEqual(
            {r["day"] for r in rows}, {date(2026, 11, 8), date(2026, 11, 9)}
        )
        self.assertTrue(any(r["scope"] == "Next-day lunch" for r in rows))

    def test_settings_validation_keeps_fresh_categories_out_of_monthly_shop(self):
        value = monthly.defaults()
        value["shops"]["Meat"] = "Main supermarket shop"
        with self.assertRaises(ValueError):
            monthly.validate(value)
        with self.assertRaises(ValueError):
            monthly.store().update(lambda s: s.update(weekly_day=8))
        self.assertFalse(monthly.FILE.exists())

    def test_bought_components_are_included_once_and_unknown_amounts_are_marked(self):
        r = recipe("With mayo")
        r["prep_components"] = [{"id": "mayonnaise"}]
        meal = {"date": TODAY.isoformat(), "kind": "recipe", "recipe": r}
        batch = {
            "id": "mayonnaise",
            "name": "Mayonnaise",
            "uses": [{"day": TODAY.isoformat(), "recipe": "With mayo", "amount": None}],
        }
        with patch.object(
            planner,
            "build_sunday_prep",
            return_value=[{"id": "mayonnaise", "action": "buy"}],
        ):
            rows = monthly.component_purchases([meal], {"batches": [batch]})
            self.assertEqual(rows[0]["line"], "Mayonnaise (amount unspecified)")
            meal["recipe"]["ingredients"].append("2 tbsp mayonnaise")
            self.assertEqual(
                monthly.component_purchases([meal], {"batches": [batch]}), []
            )

    def test_component_buy_make_follows_each_actual_week_not_month_wide_repetition(
        self,
    ):
        meals = [
            {"date": "2026-11-08", "kind": "recipe", "recipe": recipe("A")},
            {"date": "2026-11-15", "kind": "recipe", "recipe": recipe("B")},
        ]
        batches = {
            "batches": [
                {
                    "id": "pesto",
                    "name": "Pesto",
                    "uses": [
                        {
                            "day": m["date"],
                            "recipe": m["recipe"]["name"],
                            "amount": None,
                        }
                        for m in meals
                    ],
                }
            ]
        }
        with patch.object(
            planner,
            "build_sunday_prep",
            side_effect=[
                [{"id": "pesto", "action": "buy"}],
                [{"id": "pesto", "action": "make"}],
            ],
        ):
            result = monthly.component_purchases(meals, batches)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["day"], date(2026, 11, 8))

    def test_invalid_allergen_preferences_fail_before_creating_menus(self):
        write_json(planner.PREFERENCES_FILE, {"excluded_allergens": "milk"})
        with self.assertRaises(ValueError):
            monthly.generate("2026-11", TODAY)
        self.assertFalse(planner.PLANS_DIR.exists())


class MonthlyWebTests(MonthlyFixture, TestCase):
    def setUp(self):
        super().setUp()
        from flask import Flask, session, request, abort, redirect
        from functools import wraps
        from jinja2 import ChoiceLoader, DictLoader
        from web_control.monthly_meals import register

        self.app = Flask(
            __name__,
            template_folder=str(Path("web_control/templates").resolve()),
            static_folder=str(Path("web_control/static").resolve()),
        )
        self.app.secret_key = "test-only-monthly"
        self.app.config["TESTING"] = True
        self.app.jinja_loader = ChoiceLoader(
            [DictLoader({"navigation.html": ""}), self.app.jinja_loader]
        )
        self.app.jinja_env.globals["csrf_token"] = lambda: session.get("csrf_token", "")
        self.app.add_url_rule("/meals", "meals_page", lambda: "Meals")

        @self.app.before_request
        def csrf():
            if request.method == "POST" and request.form.get(
                "csrf_token"
            ) != session.get("csrf_token", "missing"):
                abort(403)

        def login_required(func):
            @wraps(func)
            def wrapped(*a, **kw):
                return (
                    func(*a, **kw)
                    if session.get("authenticated")
                    else redirect("/login")
                )

            return wrapped

        register(self.app, login_required)
        self.client = self.app.test_client()
        self.clock = patch("web_control.monthly_meals.uk_today", return_value=TODAY)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def login(self):
        with self.client.session_transaction() as session:
            session.update(authenticated=True, csrf_token="token")

    def post(self, path, **values):
        return self.client.post(
            "/meals/month/" + path,
            data=dict(csrf_token="token", month="2026-11", **values),
        )

    def test_web_requires_login_csrf_and_get_never_generates_a_menu(self):
        self.assertEqual(self.client.get("/meals/month").status_code, 302)
        self.login()
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No external collection"),
        ):
            page = self.client.get("/meals/month?month=2026-11")
        self.assertEqual(page.status_code, 200)
        self.assertFalse(planner.PLANS_DIR.exists())
        self.assertEqual(
            self.client.post(
                "/meals/month/generate", data=dict(month="2026-11")
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/meals/month?month=2030-11").status_code, 400)

    def test_month_web_forms_create_change_and_regroup_the_same_plans(self):
        self.login()
        self.assertEqual(self.post("generate").status_code, 302)
        response = self.client.get("/meals/month?month=2026-11")
        self.assertIn(b"Butcher", response.data)
        self.assertIn(b"Greengrocer", response.data)
        self.post("meal", day="2026-11-10", recipe="Chicken 1")
        self.assertEqual(
            next(
                m["recipe"]["name"]
                for m in planner.load_plan_for(date(2026, 11, 10), raw=True)["meals"]
                if m["date"] == "2026-11-10"
            ),
            "Chicken 1",
        )
        shops = {
            f"shop_{i}": s for i, s in enumerate(monthly.defaults()["shops"].values())
        }
        shops["shop_4"] = "Local shop"
        self.post("settings", weekly_day="6", veg_topup="on", veg_day="3", **shops)
        self.assertEqual(
            monthly.store().read()["shops"]["Fresh essentials"], "Local shop"
        )
        self.post("ingredient", ingredient="carrot", category="Fresh essentials")
        self.assertEqual(
            monthly.store().read()["overrides"]["carrot"], "Fresh essentials"
        )

    def test_calendar_shows_lunch_on_its_own_day_across_month_boundary(self):
        from meals import household

        self.login()
        previous = date(2026, 10, 31)
        sunday = date(2026, 11, 1)
        dinner = recipe("Saturday tray bake")
        dinner["lunch"] = {
            "name": "Sunday leftover wrap",
            "overview": "Reserve a portion.",
            "extra_ingredients": ["1 tortilla"],
        }
        self.save(
            previous, [dict(date=previous.isoformat(), kind="recipe", recipe=dinner)]
        )
        self.save(
            sunday,
            [
                dict(
                    date=sunday.isoformat(), kind="recipe", recipe=recipe("Sunday soup")
                )
            ],
        )
        view = monthly.report("2026-11", sunday)
        self.assertEqual(view["days"][0]["lunch"]["name"], "Sunday leftover wrap")
        self.assertEqual(
            view["days"][0]["lunch"]["previous_dinner"], "Saturday tray bake"
        )
        self.assertEqual(view["days"][2]["lunch"]["name"], "No lunch planned")
        page = self.client.get("/meals/month?month=2026-11")
        self.assertIn(b"Lunch: Sunday leftover wrap", page.data)
        self.assertIn(b"Dinner: Sunday soup", page.data)
        write_json(
            planner.OVERRIDES_FILE,
            {
                sunday.isoformat(): {
                    "lunch": {"type": "buy_lunch", "name": "Cafe lunch"}
                }
            },
        )
        self.assertEqual(
            monthly.report("2026-11", sunday)["days"][0]["lunch"]["name"], "Cafe lunch"
        )
        household.store().update(
            lambda s: s.update(
                configured=True, absences={sunday.isoformat(): {"legacy-0": ["lunch"]}}
            )
        )
        self.assertEqual(
            monthly.report("2026-11", sunday)["days"][0]["lunch"]["name"],
            "No lunch needed",
        )

    def test_shop_uses_saved_preference_and_only_transfers_reviewed_rows(self):
        from meals import supermarket

        self.assertEqual(self.client.get("/meals/shop").status_code, 302)
        self.login()
        shops = {
            f"shop_{i}": shop
            for i, shop in enumerate(monthly.defaults()["shops"].values())
        }
        self.post("settings", retailer="ocado", **shops)
        self.assertEqual(monthly.store().read()["retailer"], "ocado")
        self.post("settings", retailer="https://unexpected.example", **shops)
        self.assertEqual(monthly.store().read()["retailer"], "ocado")
        self.post("generate")
        view = monthly.report("2026-11")
        visits = [v for v in view["visits"] if v["shop"] in monthly.SUPERMARKET_SHOPS]
        day = visits[0]["day"]
        rows, fingerprint = supermarket.review(
            [v for v in visits if v["day"] == day], "ocado"
        )
        landing = supermarket.TRANSFER_URL + "/" + "a" * 32 + "/landing"
        with patch.object(supermarket, "transfer", return_value=landing) as send:
            page = self.client.get("/meals/shop?month=2026-11")
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"Shop at Ocado", page.data)
            self.assertIn(b"https://www.ocado.com/search?", page.data)
            self.assertNotIn(b"chicken breast", page.data)
            self.assertNotIn(b"carrot", page.data)
            for supplier, expected, excluded in (
                ("Butcher", b"chicken breast", b"carrot"),
                ("Greengrocer", b"carrot", b"chicken breast"),
            ):
                local = self.client.get(
                    "/meals/shop", query_string=dict(month="2026-11", supplier=supplier)
                )
                self.assertIn(expected, local.data)
                self.assertNotIn(excluded, local.data)
                self.assertNotIn(b"https://www.ocado.com", local.data)
                self.assertEqual(
                    self.client.post(
                        "/meals/shop",
                        data=dict(
                            month="2026-11",
                            supplier=supplier,
                            csrf_token="token",
                        ),
                    ).status_code,
                    405,
                )
            data = dict(
                month="2026-11",
                day=day.isoformat(),
                item=rows[0]["id"],
                fingerprint=fingerprint,
            )
            self.assertEqual(
                self.client.post("/meals/shop", data=data).status_code, 403
            )
            data.update(csrf_token="token")
            self.client.post("/meals/shop", data=data)
            self.client.post(
                "/meals/shop", data=dict(data, confirm_share="yes", fingerprint="stale")
            )
            self.client.post(
                "/meals/shop", data=dict(data, confirm_share="yes", item="not-reviewed")
            )
            send.assert_not_called()
            page = self.client.post("/meals/shop", data=dict(data, confirm_share="yes"))
            send.assert_called_once_with("ocado", [rows[0]["amount"]])
            self.assertIn(landing.encode(), page.data)
            self.assertIn(b"Your order has not been placed.", page.data)

    def test_dated_tasks_refresh_when_all_diners_skip_dinner(self):
        from actions import checklists
        from meals import household, shopping_tasks

        self.login()
        household.store().update(
            lambda s: s.update(configured=True, breakfast_enabled=False)
        )
        day = date(2026, 11, 7)
        self.save(day, [dict(date=day.isoformat(), kind="recipe", recipe=recipe())])
        shopping_tasks.sync("2026-11", TODAY)
        shopping_tasks.sync("2026-11", TODAY)
        tasks = checklists.rows("tasks")
        self.assertEqual(
            {t["shop_supplier"] for t in tasks}, {"Butcher", "Greengrocer"}
        )
        self.assertEqual([t["due"] for t in tasks], [day.isoformat()] * 2)
        checklists.update("tasks", "toggle", tasks[0]["id"])
        self.post("attendance", day=day.isoformat(), absent="legacy-0:dinner")
        self.assertEqual(len(checklists.rows("tasks")), 1)
        self.assertTrue(checklists.rows("tasks")[0]["completed"])
        view = monthly.report("2026-11")
        self.assertEqual(
            next(row["meal"]["kind"] for row in view["days"] if row["day"] == day),
            "skipped",
        )
        self.assertEqual(view["visits"], [])
        self.post("attendance", day=day.isoformat())
        self.assertEqual(len(checklists.rows("tasks")), 2)
        self.assertTrue(
            next(t for t in checklists.rows("tasks") if t["id"] == tasks[0]["id"])[
                "completed"
            ]
        )

    def test_invalid_settings_do_not_overwrite_valid_file_and_data_is_escaped(self):
        self.login()
        monthly.store().update(lambda s: s.update(weekly_day=6))
        before = monthly.FILE.read_bytes()
        self.post("settings", weekly_day="99")
        self.assertEqual(monthly.FILE.read_bytes(), before)
        self.save(
            TODAY,
            [
                dict(
                    date=TODAY.isoformat(),
                    kind="recipe",
                    recipe=recipe("<script>alert(1)</script>"),
                )
            ],
        )
        page = self.client.get("/meals/month?month=2026-11")
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", page.data)
        self.assertNotIn(b"<script>alert(1)</script>", page.data)
