"""Form, private baseline, observation and receipt behaviour without external services."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from flask import Flask
from werkzeug.datastructures import MultiDict
from web_control.long_term import register
from finance.long_range.config import defaults, account
from finance.long_range import store as records

TODAY = date(2026, 10, 26)


def form(config, action="forecast"):
    pairs = [
        (k, str(v))
        for k, v in config.items()
        if k
        not in ("accounts", "events", "goals", "isa_enabled", "invest_without_salary")
    ]
    for key in ("isa_enabled", "invest_without_salary"):
        if config[key]:
            pairs.append((key, "on"))
    for a in config["accounts"]:
        for key, val in a.items():
            pairs.append(
                (
                    "a_" + key,
                    ("yes" if val else "no") if type(val) is bool else str(val),
                )
            )
    for prefix, key in [("e", "events"), ("g", "goals")]:
        for row in config[key]:
            for field, value in row.items():
                pairs.append(
                    (
                        prefix + "_" + field,
                        ("yes" if value else "no")
                        if type(value) is bool
                        else str(value),
                    )
                )
    pairs.append(("action", action))
    return MultiDict(pairs)


class LongRangeWebTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(records, "FILE", Path(self.tmp.name) / "plans.json").start()
        patch("web_control.long_term.uk_today", return_value=TODAY).start()
        app = Flask(
            __name__, template_folder=str(Path("web_control/templates").resolve())
        )
        app.secret_key = "test"
        app.jinja_env.globals["csrf_token"] = lambda: "test"
        # Other navigation endpoints are outside this focused test app.
        app.jinja_env.globals["url_for"] = lambda endpoint, **kwargs: (
            "/stub/" + endpoint
        )
        self.prints = []
        register(app, lambda f: f, lambda args: (self.prints.append(args) or True, ""))
        self.client = app.test_client()
        self.config = defaults(TODAY)
        self.config.update(years="2", salary="3000", bills="1000", spending="700")
        self.config["accounts"].append(
            account("Example investment", "investment", expected="5", high="8")
        )

    def test_render_generate_validation_and_year_pagination(self):
        self.assertEqual(self.client.get("/finance/long-term").status_code, 200)
        response = self.client.post("/finance/long-term", data=form(self.config))
        self.assertEqual(response.status_code, 200, response.data[:1000])
        self.assertIn(b"Where the plan could lead", response.data)
        self.assertIn(b"Why did each balance change?", response.data)
        self.assertIn(b"Year 2", response.data)
        bad = dict(self.config, years="41")
        self.assertEqual(
            self.client.post("/finance/long-term", data=form(bad)).status_code, 400
        )

    def test_saved_baseline_actual_observation_and_rebase(self):
        response = self.client.post(
            "/finance/long-term", data=form(self.config, "save")
        )
        self.assertEqual(response.status_code, 302)
        state = records.store().read()
        key = next(iter(state["plans"]))
        r = self.client.post(
            "/finance/long-term/observe",
            data=dict(
                account=self.config["accounts"][0]["id"],
                date=str(TODAY),
                balance="1200",
                note="Recorded",
                plan=key,
            ),
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            records.store().read()["observations"][0]["balance"], "1200.00"
        )
        r = self.client.post("/finance/long-term", data=form(self.config, "rebase"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"1200.00", r.data)
        self.assertEqual(
            records.store().read()["plans"][key]["config"]["accounts"][0]["balance"],
            "0",
        )

    def test_receipt_is_explicitly_archived_before_printing(self):
        from receipt import archive

        with patch.object(archive, "DIRECTORY", Path(self.tmp.name) / "archive"):
            response = self.client.post(
                "/finance/long-term", data=form(self.config, "receipt")
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.prints, [])
            response = self.client.post("/finance/long-term/print")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.prints[0][0], "--archive")
            item = archive.load(self.prints[0][1])
            self.assertIn("LONG-TERM PLANNING", item["pages"]["finance"])
