from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import json
import runpy

from finance import (
    savings_goals as goals,
    wealth_history,
    account_editor,
    visuals,
    check_changes,
)
from finance.test_receipt import build
from receipt.capture import RecordingPrinter
from receipt.paper import estimate
from web_control.daily_focus import build as priorities

TODAY = date(2026, 10, 15)
FIXTURE = runpy.run_path(
    str(Path(__file__).with_name("test_compact_finance_receipt.py"))
)


class FinanceClarityTests(TestCase):
    def test_charts_match_authoritative_totals_and_do_not_mutate(self):
        base = FIXTURE["source"]()
        values = FIXTURE["values"]()
        result = build(base, values, TODAY)
        original = deepcopy(result)
        charts = visuals.test_charts(result, TODAY, [("Current", result)])
        self.assertEqual(len(charts["lines"]), 4)
        savings = next(c for c in charts["lines"] if c["key"] == "test-savings")
        self.assertEqual(
            savings["series"][0]["data"][-1]["value"],
            f"£{result['account_plan']['accounts'][0]['projected']:,.2f}",
        )
        debt = next(c for c in charts["lines"] if c["key"] == "test-amex")
        self.assertEqual(
            debt["series"][0]["data"][-1]["value"],
            f"£{result['forecast']['card_end']:,.2f}",
        )
        allocation = charts["allocation"]["rows"]
        self.assertEqual(
            allocation[0]["value"],
            f"£{result['forecast']['payments'][0]['costs']:,.2f}",
        )
        self.assertAlmostEqual(sum(r["percent"] for r in allocation), 100)
        self.assertEqual(result, original)
        json.dumps(charts)  # Archive-safe data, no Decimal/date objects.

    def test_main_cash_charts_cover_30_and_90_days_with_same_reserve(self):
        projection = dict(
            valid=True,
            cash=D(1500),
            buffer=D(1000),
            daily=D(10),
            events=[],
            horizon=1826,
        )
        rows = [
            dict(
                id="a",
                name="Rent",
                date="2026-10-20",
                repeat="monthly",
                enabled=True,
                end_date="",
                amount="100",
            )
        ]
        for days in (30, 90):
            chart = visuals.main_cash(projection, rows, TODAY, days)
            self.assertEqual(chart["end"], (TODAY + timedelta(days=days)).isoformat())
            self.assertEqual(
                chart["series"][0]["data"][-1]["value"], f"£{1500 - days * 10:,.2f}"
            )
            self.assertEqual(chart["series"][-1]["data"][-1]["value"], "£1,000.00")
            expected = 1500 - days * 10 + (100 if days == 30 else 300)
            self.assertEqual(
                chart["series"][1]["data"][-1]["value"], f"£{expected:,.2f}"
            )
        self.assertIsNone(visuals.main_cash(dict(projection, valid=False), rows, TODAY))

    def test_unified_editor_retains_identity_and_clears_optional_limits(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(goals, "FILE", Path(folder) / "goals.json"),
            patch.object(wealth_history, "HISTORY_FILE", Path(folder) / "wealth.json"),
        ):
            wealth_history.record(
                "Original pot",
                "savings",
                str(TODAY),
                100,
                deposits=20,
                withdrawals=0,
                today=TODAY,
            )
            key = goals.identity("Original pot", "savings")
            values = dict(
                display_name="Holiday pot",
                type="savings",
                target="",
                balance_limit="",
                monthly_share="0",
                interest_rate="3.5",
                rate_date=str(TODAY),
                balance="120",
                balance_date=str(TODAY),
            )
            account_editor.save(key, values, wealth_history.review(TODAY), TODAY)
            state = goals.load()["accounts"][key]
            self.assertEqual(state["name"], "Original pot")
            self.assertEqual(state["display_name"], "Holiday pot")
            self.assertEqual(wealth_history.load_history()[0]["deposits"], "20.00")
            self.assertIsNone(state["target"])
            self.assertIsNone(state["balance_limit"])
            self.assertEqual(
                wealth_history.review(TODAY)["accounts"][0]["balance"], D(120)
            )
            original = goals.FILE.read_bytes()
            history = wealth_history.HISTORY_FILE.read_bytes()
            for changes in (
                dict(monthly_share="101"),
                dict(balance_date="2030-01-01"),
                dict(interest_rate="101"),
            ):
                with self.assertRaises(ValueError):
                    account_editor.save(
                        key,
                        dict(values, **changes),
                        wealth_history.review(TODAY),
                        TODAY,
                    )
                self.assertEqual(goals.FILE.read_bytes(), original)
                self.assertEqual(wealth_history.HISTORY_FILE.read_bytes(), history)
            with patch("finance.savings_goals.write_json", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    account_editor.save(
                        key,
                        dict(values, balance="150"),
                        wealth_history.review(TODAY),
                        TODAY,
                    )
            self.assertEqual(wealth_history.HISTORY_FILE.read_bytes(), history)

    def test_all_accounts_show_without_targets(self):
        from flask import Flask, render_template

        names = ["Pot " + str(i) for i in range(5)]
        state = dict(
            accounts={
                goals.identity(n, "savings"): dict(
                    name=n,
                    kind="savings",
                    type="savings",
                    target="500" if i < 3 else None,
                )
                for i, n in enumerate(names)
            },
            entries=[],
            years={},
        )
        wealth = {
            "accounts": [
                dict(
                    name=n, kind="savings", balance=D(100), latest={"date": str(TODAY)}
                )
                for n in names
            ]
        }
        view = goals.review(wealth, state=state, on=TODAY, bond_balances=[])
        app = Flask(
            __name__,
            template_folder=str(
                Path(__file__).resolve().parents[1] / "web_control/templates"
            ),
        )
        app.add_url_rule("/goals", "savings_goals_page", lambda: "")
        app.add_url_rule(
            "/account/<account>", "savings_account_editor", lambda account: ""
        )
        with app.test_request_context():
            html = render_template("savings_goal_summary.html", goals=view)
        for name in names:
            self.assertIn(name, html)
        self.assertEqual(html.count("No target set"), 2)

    def test_change_checkpoints_are_read_only_on_views_and_do_not_invent_growth(self):
        def model(cash, scope=None):
            return dict(
                projection=dict(
                    cash=D(cash), events=[], valid=True, cash_run_out_date=None
                ),
                observation={
                    "summary": {
                        "bank_data_status": "complete",
                        "collection_scope": scope,
                    }
                },
                insights={"observation": {"card_debt": "50"}},
                wealth={"accounts": []},
            )

        with (
            TemporaryDirectory() as folder,
            patch.object(check_changes, "FILE", Path(folder) / "checks.json"),
        ):
            check_changes.record(model(100), "2026-10-15T12:00:00+00:00", TODAY)
            check_changes.record(model(120), "2026-10-15T13:00:00+00:00", TODAY)
            before = check_changes.FILE.read_bytes()
            self.assertIn("+£20.00", check_changes.view()["changes"][0])
            self.assertEqual(check_changes.FILE.read_bytes(), before)
            check_changes.record(
                model(900, {"sources": ["changed"]}), "2026-10-15T14:00:00+00:00", TODAY
            )
            self.assertEqual(len(check_changes.view()["changes"]), 1)
            self.assertIn("not directly comparable", check_changes.view()["changes"][0])

    def test_today_priority_explanations_and_no_duplicate_mot(self):
        row = dict(registration="AB12CDE", mot_expiry="2026-10-22")
        result = priorities(
            TODAY,
            [dict(id="task", title="Book MOT for AB12CDE", due="2026-10-01")],
            {},
            ["[ ] Put out recycling today"],
            [row],
            [],
            {},
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r["why"] for r in result))
        self.assertIn("30 days", next(r["why"] for r in result if "MOT" in r["title"]))

    def test_news_spacing_saves_lines_without_removing_headlines(self):
        from receipt.news_renderers import _print_news_stories

        stories = [dict(headline=f"Headline {n}", summary="") for n in range(3)]

        def output(saver):
            rec = RecordingPrinter(Mock(), defer=True, paper_saver=saver)
            context = {
                "left": lambda p, t: p.text(t + "\n"),
                "print_line": lambda p, c: p.text("-" * 42 + "\n"),
                "print_wrapped": lambda p, t, width: p.text(t + "\n"),
                "_news_summary_is_useful": lambda *args: False,
            }
            for name in ("UK NEWS", "LOCAL NEWS", "SPORT"):
                _print_news_stories(
                    rec, name, stories, include_summary=False, _context=context
                )
            return "".join(rec.lines)

        full, short = output(False), output(True)
        self.assertEqual(len(full.splitlines()) - len(short.splitlines()), 6)
        for n in range(3):
            self.assertEqual(full.count(f"Headline {n}"), short.count(f"Headline {n}"))

    def test_paper_spacing_preserves_all_words_and_physical_capture_match(self):
        target = Mock()
        rec = RecordingPrinter(target, defer=True, paper_saver=True)
        for text in (
            "\n\n",
            "TITLE\n",
            "\n\n\n",
            "Warning: do not resend\n",
            "-" * 42 + "\n",
            "\n",
            "-" * 42 + "\n",
            "[ ] Task\n",
        ):
            rec.text(text)
        text = "".join(rec.lines)
        self.assertNotIn("\n\n\n", text)
        self.assertEqual(text.count("-" * 42), 1)
        self.assertIn("Warning: do not resend", text)
        self.assertIn("[ ] Task", text)
        rec.send()
        self.assertEqual(
            "".join(call.args[0] for call in target.text.call_args_list), text
        )
        compact = estimate({"actions": text})
        full = estimate(
            {
                "actions": "TITLE\n\n\n\nWarning: do not resend\n"
                + "-" * 42
                + "\n\n"
                + "-" * 42
                + "\n[ ] Task\n"
            }
        )
        self.assertLess(compact["cm"], full["cm"])
