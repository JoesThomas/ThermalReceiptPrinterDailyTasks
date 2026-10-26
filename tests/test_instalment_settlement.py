"""Actual settlements are retained, reversible and excluded from future payments."""

from copy import deepcopy
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from flask import Flask
from finance import instalment_settlement as settlement
from finance.early_payoff import options
from finance.projection import payment_schedule
from finance.subscription_store import load, save, validate
from web_control.instalment_settlement import register

TODAY = date(2026, 10, 26)


def state():
    return dict(
        monthly=[dict(name="Headphones plan", amount=25, due_day=1)],
        yearly=[],
        instalments=[
            dict(
                name="Headphones plan",
                amount=25,
                balance=100,
                payments_remaining=4,
                next_payment="2026-11-01",
                schedule=[dict(date="2026-11-01", amount=25)],
                paid_to_date=50,
            )
        ],
    )


class SettlementTests(TestCase):
    def test_settle_preserves_history_and_reopen_restores_forecasts(self):
        value = state()
        before = deepcopy(value)
        item = value["instalments"][0]
        monthly_key = settlement.linked_monthly(item, value["monthly"])[0]["key"]
        settlement.settle(
            value,
            0,
            settlement.identity(item),
            str(TODAY),
            TODAY,
            monthly_key=monthly_key,
        )
        validate(value)
        self.assertEqual(item["balance"], 0)
        self.assertEqual(item["remaining_balance"], 0)
        self.assertEqual(item["schedule"], before["instalments"][0]["schedule"])
        self.assertEqual(item["paid_to_date"], 50)
        self.assertEqual(options(value["instalments"]), [])
        self.assertTrue(settlement.is_settled(value["monthly"][0], TODAY))
        self.assertEqual(payment_schedule(value["monthly"], [], [], {}, TODAY)[0], [])
        settlement.reopen(value, 0, settlement.identity(item))
        validate(value)
        history = item.pop("settlement_history")
        self.assertEqual(len(history), 1)
        self.assertEqual(value, before)
        self.assertTrue(options(value["instalments"]))
        self.assertTrue(payment_schedule(value["monthly"], [], [], {}, TODAY)[0])

    def test_linking_is_optional_unique_and_does_not_hide_unrelated_bills(self):
        value = state()
        item = value["instalments"][0]
        settlement.settle(value, 0, settlement.identity(item), str(TODAY), TODAY)
        self.assertFalse(settlement.is_settled(value["monthly"][0], TODAY))
        self.assertTrue(payment_schedule(value["monthly"], [], [], {}, TODAY)[0])
        value = state()
        value["monthly"].append(deepcopy(value["monthly"][0]))
        self.assertEqual(
            settlement.linked_monthly(value["instalments"][0], value["monthly"]), []
        )
        value["instalments"][0]["name"] = "Amazon"
        self.assertEqual(
            settlement.linked_monthly(value["instalments"][0], value["monthly"]), []
        )

    def test_stale_and_future_confirmations_do_not_mutate(self):
        for key, on, monthly in [
            ("bad", str(TODAY), None),
            (None, "2026-10-27", None),
            (None, str(TODAY), "bad"),
        ]:
            value = state()
            before = deepcopy(value)
            with self.assertRaises(ValueError):
                settlement.settle(
                    value,
                    0,
                    key or settlement.identity(value["instalments"][0]),
                    on,
                    TODAY,
                    monthly_key=monthly,
                )
            self.assertEqual(value, before)

    def test_routes_persist_and_stale_retries_do_not_reapply(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "subscriptions.json"
            save(path, state())
            app = Flask(__name__)
            app.secret_key = "test"
            app.add_url_rule("/", endpoint="index", view_func=lambda: "Accounts")
            register(app, lambda f: f, lambda: path)
            client = app.test_client()
            key = settlement.identity(load(path)["instalments"][0])
            body = dict(key=key, date="2026-10-25")
            self.assertEqual(
                client.post("/instalment/0/settle", data=body).status_code, 302
            )
            value = load(path)
            self.assertEqual(value["instalments"][0]["settled_on"], "2026-10-25")
            client.post("/instalment/0/settle", data=body)
            self.assertEqual(load(path), value)
            client.post(
                "/instalment/0/reopen",
                data=dict(key=settlement.identity(value["instalments"][0])),
            )
            self.assertNotIn("settled_on", load(path)["instalments"][0])

    def test_invalid_metadata_is_rejected(self):
        value = state()
        settlement.settle(
            value, 0, settlement.identity(value["instalments"][0]), str(TODAY), TODAY
        )
        for change in [
            dict(remaining_balance=10),
            dict(settlement={"previous": []}),
            dict(settlement_history=[False]),
        ]:
            broken = deepcopy(value)
            broken["instalments"][0].update(change)
            with self.assertRaises(ValueError):
                validate(broken)
