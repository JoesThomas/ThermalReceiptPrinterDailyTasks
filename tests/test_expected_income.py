from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from finance import expected_income as income
from web_control.private_backup import _validate_file

TODAY = date(2026, 10, 15)


def payment(**changes):
    return dict(
        dict(
            id="a" * 12,
            name="Property rent",
            amount="100.00",
            date="2026-10-31",
            repeat="monthly",
            end_date="",
            enabled=True,
        ),
        **changes,
    )


def projection(**changes):
    return dict(
        dict(
            valid=True,
            cash=D(1200),
            buffer=D(1000),
            daily=D(10),
            events=[],
            horizon=40,
            horizon_end_date=TODAY + timedelta(days=40),
            horizon_duration="40 days",
        ),
        **changes,
    )


class ExpectedIncomeTests(TestCase):
    def test_recurrences_short_months_month_end_year_end_and_leap_year(self):
        end = date(2027, 4, 30)
        rows = income.scheduled(
            [payment(repeat="month_end", date="2026-10-20")], TODAY, end
        )
        self.assertEqual(
            [e["date"] for e in rows],
            [
                date(2026, 10, 31),
                date(2026, 11, 30),
                date(2026, 12, 31),
                date(2027, 1, 31),
                date(2027, 2, 28),
                date(2027, 3, 31),
                date(2027, 4, 30),
            ],
        )
        rows = income.scheduled([payment(date="2027-01-30")], TODAY, date(2027, 3, 31))
        self.assertEqual(
            [e["date"] for e in rows],
            [date(2027, 1, 30), date(2027, 2, 28), date(2027, 3, 30)],
        )
        rows = income.scheduled(
            [payment(date="2024-02-29", repeat="yearly")], TODAY, date(2028, 3, 1)
        )
        self.assertEqual(
            [e["date"] for e in rows], [date(2027, 2, 28), date(2028, 2, 29)]
        )

    def test_future_only_disabled_one_off_and_inclusive_end_date(self):
        rows = [
            payment(date=str(TODAY), repeat="once"),
            payment(id="b" * 12, date="2026-10-16", repeat="once"),
            payment(id="c" * 12, enabled=False),
        ]
        events = income.scheduled(rows, TODAY, date(2026, 12, 31))
        self.assertEqual([e["id"] for e in events], ["b" * 12])
        events = income.scheduled(
            [payment(end_date="2026-11-30")], TODAY, date(2031, 10, 15)
        )
        self.assertEqual(
            [e["date"] for e in events], [date(2026, 10, 31), date(2026, 11, 30)]
        )
        self.assertEqual(
            income.scheduled([payment(date="2032-01-01")], TODAY, date(2031, 10, 15)),
            [],
        )

    def test_separate_projection_preserves_baseline_and_early_shortfall(self):
        base = projection()
        original = deepcopy(base)
        events = income.scheduled(
            [payment(date="2026-10-20", repeat="once")], TODAY, base["horizon_end_date"]
        )
        with_income = income.compare(base, events, TODAY)
        without_income = income.compare(base, [], TODAY)
        self.assertEqual(without_income["run_out"], TODAY + timedelta(days=21))
        self.assertEqual(with_income["run_out"], TODAY + timedelta(days=31))
        self.assertEqual(with_income["end_cash"] - without_income["end_cash"], D(100))
        self.assertEqual(base, original)
        early = income.compare(projection(cash=D(1010)), events, TODAY)
        self.assertEqual(early["run_out"], TODAY + timedelta(days=2))
        self.assertEqual(
            income.compare(projection(valid=False), events, TODAY), {"valid": False}
        )

    def test_private_updates_validation_pause_delete_and_backup(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(income, "FILE", Path(folder) / "income.json"),
        ):
            form = dict(
                name="Property rent",
                amount="100",
                date="2026-10-31",
                repeat="month_end",
                end_date="",
                enabled="on",
            )
            income.save(form)
            row = income.load()["payments"][0]
            self.assertEqual(income.FILE.stat().st_mode & 0o777, 0o600)
            _validate_file("expected_income.json", income.load())
            original = income.FILE.read_bytes()
            for fields in (
                {"amount": "-1"},
                {"amount": "NaN"},
                {"amount": "100.001"},
                {"repeat": "salary"},
                {"date": "2026-02-30"},
                {"end_date": "2026-01-01"},
                {"name": ""},
            ):
                with self.assertRaises((ValueError, TypeError)):
                    income.save(dict(form, id=row["id"], **fields))
                self.assertEqual(income.FILE.read_bytes(), original)
            income.save(dict(form, id=row["id"], enabled=""))
            self.assertEqual(income.view(projection(), TODAY)["events"], [])
            income.save({"id": row["id"]}, action="delete")
            self.assertEqual(income.load()["payments"], [])
            income.FILE.write_text("broken")
            self.assertIn("error", income.view(projection(), TODAY))
            with self.assertRaises(ValueError):
                income.save(form)
            self.assertEqual(income.FILE.read_text(), "broken")

    def test_30_day_card_is_shown_only_before_any_shortfall(self):
        from flask import Flask, render_template

        app = Flask(
            __name__,
            template_folder=str(
                Path(__file__).resolve().parents[1] / "web_control/templates"
            ),
        )
        app.add_url_rule("/finance/expected-income", "save_expected_income", lambda: "")
        app.jinja_env.globals["csrf_token"] = lambda: "test"
        with (
            TemporaryDirectory() as folder,
            patch.object(income, "FILE", Path(folder) / "income.json"),
        ):
            income.save(
                dict(
                    name="Property rent",
                    amount="100",
                    date="2026-10-20",
                    repeat="monthly",
                    enabled="on",
                )
            )
            base = projection(
                cash=D(2000), horizon=1826, horizon_end_date=date(2031, 10, 15)
            )
            original = deepcopy(base)
            view = income.view(base, TODAY)
            self.assertEqual(view["end"], date(2026, 11, 14))
            self.assertEqual(view["total"], D(100))
            self.assertEqual(view["end_cash"], D(1800))
            self.assertTrue(view["show_end_balance"])
            self.assertEqual(base, original)
            with app.test_request_context():
                html = render_template(
                    "expected_income.html", expected_income=view, projection=base
                )
            self.assertIn("Projected bank cash on 14 Nov 2026", html)
            self.assertNotIn("2031", html)
            shortfall = income.view(projection(cash=D(1010)), TODAY)
            self.assertFalse(shortfall["show_end_balance"])
            with app.test_request_context():
                html = render_template(
                    "expected_income.html", expected_income=shortfall, projection=base
                )
            self.assertNotIn("Projected bank cash on", html)
            self.assertIn("First projected shortfall: 17 Oct 2026", html)
            text = income.receipt_summary(projection(cash=D(1010)), TODAY)
            self.assertNotIn("Projected bank cash", text)
            self.assertIn("First shortfall: 17 Oct 2026", text)

    def test_later_payments_remain_manageable_without_a_30_day_projection(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(income, "FILE", Path(folder) / "income.json"),
        ):
            income.save(
                dict(
                    name="Later payment",
                    amount="100",
                    date="2026-11-20",
                    repeat="once",
                    enabled="on",
                )
            )
            view = income.view(projection(), TODAY)
            self.assertEqual(view["events"], [])
            self.assertEqual(view["rows"][0]["next_date"], date(2026, 11, 20))
            self.assertEqual(income.receipt_summary(projection(), TODAY), "")

    def test_receipt_uses_same_projection_and_retains_40_columns(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(income, "FILE", Path(folder) / "income.json"),
        ):
            self.assertEqual(income.receipt_summary(projection(), TODAY), "")
            income.save(
                dict(
                    name="Property rent",
                    amount="100",
                    date="2026-10-20",
                    repeat="monthly",
                    end_date="",
                    enabled="on",
                )
            )
            view = income.view(projection(cash=D(1100)), TODAY)
            text = income.receipt_summary(projection(cash=D(1100)), TODAY)
            self.assertIn("EXPECTED INCOME / NO SALARY", text)
            self.assertIn("Property rent", text)
            self.assertIn(f"First shortfall: {view['run_out']:%d %b %Y}", text)
            self.assertTrue(all(len(line) <= 40 for line in text.splitlines()))
            self.assertIn(
                "Projection unavailable",
                income.receipt_summary(projection(valid=False), TODAY),
            )
