from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from flask import Flask, render_template
from finance import savings_goals as goals
from web_control.savings_goal_tools import register


class SavingsInterestCardTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(goals, "FILE", Path(self.directory.name) / "goals.json").start()
        self.row = dict(
            name="Example savings pot",
            kind="savings",
            balance=Decimal("250.00"),
            latest=dict(date="2026-10-15", source="manual"),
            change=None,
            chart=[],
            entries=[],
        )
        self.wealth = dict(
            accounts=[self.row],
            savings=Decimal("250.00"),
            investments=0,
            total=Decimal("250.00"),
            month="2026-10",
        )
        self.app = Flask(
            __name__, template_folder=str(Path("web_control/templates").resolve())
        )
        self.app.secret_key = "test"
        self.app.jinja_env.globals["csrf_token"] = lambda: "test"
        register(self.app, lambda function: function, lambda: self.wealth)
        self.app.add_url_rule(
            "/savings",
            endpoint="savings_review",
            view_func=lambda: render_template(
                "wealth_section.html",
                wealth=self.wealth,
                wealth_error=None,
                today=date(2026, 10, 15),
            ),
        )
        for endpoint in ["premium_bonds_page", "savings_record", "savings_delete"]:
            self.app.add_url_rule(
                "/stub/" + endpoint, endpoint=endpoint, view_func=lambda: ""
            )
        self.client = self.app.test_client()
        self.key = goals.identity(self.row["name"], "savings")

    def save(self, **changes):
        values = dict(
            account=self.key, rate="4.5", date="2026-10-15", return_to="savings"
        )
        values.update(changes)
        return self.client.post("/savings/isa/rate", data=values)

    def test_rate_can_be_saved_directly_on_new_recorded_pot_and_is_shared(self):
        original = deepcopy(self.wealth)
        self.assertIn(b"No interest rate set", self.client.get("/savings").data)
        response = self.save()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/savings")
        saved = goals.load()
        self.assertEqual(saved["accounts"][self.key]["interest_rate"], "4.50")
        self.assertEqual(saved["accounts"][self.key]["type"], "savings")
        self.assertEqual(saved["entries"], [])
        card = self.client.get("/savings").data
        self.assertIn(b"4.50% AER", card)
        self.assertIn(b"250.00", card)
        self.assertEqual(self.wealth, original)
        # Editing through the goals page updates the same record and card.
        self.assertEqual(
            self.save(rate="3", return_to="goals").headers["Location"], "/savings/goals"
        )
        self.assertIn(b"3.00% AER", self.client.get("/savings").data)
        self.save(rate="")
        self.assertIn(b"No interest rate set", self.client.get("/savings").data)

    def test_invalid_new_rate_or_unknown_account_does_not_create_settings(self):
        for values in [dict(rate="101"), dict(rate="NaN"), dict(account="unknown")]:
            self.save(**values)
            self.assertEqual(goals.load()["accounts"], {})

    def test_saved_account_targets_limits_and_shares_survive_rate_edits(self):
        goals.account_settings(
            self.row["name"], "savings", "savings", "500", "25", "1000"
        )
        self.save()
        row = goals.load()["accounts"][self.key]
        self.assertEqual(
            (row["target"], row["monthly_share"], row["balance_limit"]),
            ("500.00", "25.00", "1000.00"),
        )
        self.assertEqual(
            self.save(return_to="https://example.com").headers["Location"],
            "/savings/goals",
        )
