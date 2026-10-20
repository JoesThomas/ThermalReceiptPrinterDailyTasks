import ast
import json
import os
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import TestCase
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from finance_trends import _window_totals_many, categorise_transaction, prepare_rules
from receipt import archive
from receipt.text import printer_safe_text
from services.parallel import collect_independent
from storage import file_lock, read_json_object, write_json

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 11)


class RepoEfficiencyTests(TestCase):
    def test_parallel_sources_overlap_and_keep_independent_failures(self):
        barrier = Barrier(3)

        def source(value):
            barrier.wait(timeout=3)
            if value == "bad":
                raise ValueError("unavailable")
            return value

        results = collect_independent(
            {name: lambda name=name: source(name) for name in ("first", "bad", "last")}
        )
        self.assertEqual(results["first"].result(), "first")
        self.assertEqual(results["last"].result(), "last")
        with self.assertRaises(ValueError):
            results["bad"].result()
        self.assertEqual(collect_independent({}), {})

    def test_information_pipeline_fetches_concurrently_and_renders_in_receipt_order(
        self,
    ):
        from receipt_settings import DEFAULT_SETTINGS, feature_enabled, display_value
        from receipt.location_settings import DEFAULT_LOCATION, validate_location

        source = ast.parse((ROOT / "services/live_pipeline.py").read_text())
        function = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_live_pipeline"
        )
        barrier = Barrier(4)
        collected = []
        rendered = []
        weather_details = []
        weather_coordinates = []
        headline_counts = []

        def collect(name):
            barrier.wait(timeout=3)
            collected.append(name)
            return name

        printer = Mock()
        printer.profile.profile_data = {"media": {"width": {"pixels": 0}}}
        settings = deepcopy(DEFAULT_SETTINGS)
        settings["display"]["weather_detail"] = "compact"
        settings["layout"] = {"detail":"compact"}
        settings["location"] = dict(DEFAULT_LOCATION, name="Edinburgh", region="Scotland", latitude=55.95, longitude=-3.19)
        settings["features"].update(
            weather=True, national_news=True, local_news=True, sport_news=True
        )
        namespace = dict(
            os=os,
            load_receipt_settings=lambda: settings,
            DEFAULT_LOCATION=DEFAULT_LOCATION,
            validate_location=validate_location,
            clear_route_cache=lambda: None,
            Usb=lambda *args: printer,
            PRINTER_VENDOR_ID=1,
            PRINTER_PRODUCT_ID=2,
            setup_printer=lambda printer: None,
            datetime=datetime,
            ZoneInfo=ZoneInfo,
            one_shot_requested=lambda *args: False,
            print_header=lambda *args: None,
            feature_enabled=feature_enabled,
            display_value=display_value,
            NEWS_HEADLINES=3,
            LOCAL_NEWS_HEADLINES=3,
            SPORT_NEWS_HEADLINES=3,
            get_weather=lambda *args: (weather_coordinates.append(args), collect("weather"))[1],
            get_top_news_headlines=lambda count: (headline_counts.append(count), collect("national"))[1],
            get_local_news_headlines=lambda *args: collect("local"),
            get_sport_news_headlines=lambda *args: collect("sport"),
            print_weather=lambda p, value, *args, **kwargs: (rendered.append(value), weather_details.append(kwargs["detail"])),
            print_news=lambda p, value: rendered.append(value),
            print_local_news=lambda p, value, *args: rendered.append(value),
            print_sport_news=lambda p, value: rendered.append(value),
            print_footer=lambda *args: None,
            cut_receipt_section=lambda *args: None,
            left=lambda *args: None,
            print_wrapped=lambda *args, **kwargs: None,
            printer_safe_text=printer_safe_text,
        )
        exec(
            compile(
                ast.Module(body=[function], type_ignores=[]), "live_pipeline.py", "exec"
            ),
            namespace,
        )
        with (
            patch("services.local_gigs.options", return_value={"enabled": False}),
            patch("receipt.preview_progress.report"),
            patch("builtins.print"),
        ):
            namespace["run_live_pipeline"](selected_pages=["information"])
        self.assertEqual(set(collected), {"weather", "national", "local", "sport"})
        self.assertEqual(rendered, ["weather", "national", "local", "sport"])
        self.assertEqual(weather_details, ["full"])
        self.assertEqual(headline_counts, [settings["display"]["news_count"]])
        self.assertEqual(headline_counts, [3])  # Legacy compact no longer caps headlines.
        self.assertEqual(weather_coordinates, [(55.95, -3.19)])

    def test_printer_cleaner_keeps_pounds_and_removes_control_sequences(self):
        self.assertEqual(
            printer_safe_text("Café £25 — “paid”\t→\r\n\x1b[31mred\x00😀"),
            'Cafe £25 - "paid"    ->\nred',
        )
        self.assertEqual(printer_safe_text(None), "")
        self.assertEqual(printer_safe_text("©®™€"), "(C)(R)(TM)EUR")

    def test_file_helper_releases_after_failure_and_uses_private_lock(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            with self.assertRaises(ValueError):
                with file_lock(path):
                    raise ValueError("cancelled")
            with file_lock(path):
                write_json(path, {"ok": True})
            self.assertEqual(path.with_suffix(".lock").stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_json_object(path), {"ok": True})
            path.write_text("[]")
            self.assertEqual(read_json_object(path), {})
            path.write_text("broken")
            self.assertEqual(read_json_object(path), {})

    def test_transaction_windows_parse_once_and_preserve_overlapping_totals(self):
        rows = [
            {"date": "2026-10-01", "description": "Cafe", "amount": -10},
            {"date": "2026-10-10", "description": "Cafe", "amount": -20},
            {"date": "bad", "description": "Cafe", "amount": -30},
        ]
        from finance_trends import _parse_date

        with patch("finance_trends._parse_date", wraps=_parse_date) as parse:
            result = _window_totals_many(
                rows,
                {"CAFE": "COFFEE"},
                [(date(2026, 10, 1), TODAY), (date(2026, 10, 5), TODAY)],
            )
        self.assertEqual(result, [{"COFFEE": 30.0}, {"COFFEE": 20.0}])
        self.assertEqual(parse.call_count, len(rows))

    def test_prepared_rules_preserve_private_precedence_and_rent_word_boundary(self):
        rules = {
            "transactions": [
                {"date": "bad", "amount": 10, "merchant": "SHOP", "category": "WRONG"},
                {
                    "date": "2026-10-11",
                    "amount": 10,
                    "merchant": "SHOP",
                    "category": "PRESENT",
                },
            ],
            "SHOP": "SHOPPING",
            "RENT": "RENT",
        }
        original = deepcopy(rules)
        prepared = prepare_rules(rules)
        self.assertEqual(
            categorise_transaction(
                {"date": str(TODAY), "description": "SHOP", "amount": -10}, prepared
            ),
            "PRESENT",
        )
        self.assertEqual(
            categorise_transaction(
                {"date": "2026-10-10", "description": "SHOP", "amount": -10}, prepared
            ),
            "SHOPPING",
        )
        self.assertEqual(
            categorise_transaction(
                {"description": "BRENTWOOD CAFE", "amount": -10}, prepared
            ),
            "OTHER",
        )
        self.assertEqual(rules, original)
        self.assertIs(prepare_rules(prepared), prepared)

    def fixture_archive(self, folder, count):
        for index in range(count):
            identifier = f"20261011T120000Z-{index:012x}"
            write_json(
                folder / (identifier + ".json"),
                {
                    "id": identifier,
                    "captured_at": "2026-10-11T12:00:00+00:00",
                    "source": "preview",
                    "pages": {
                        "finance": f"Coffee {index}" if index % 2 else f"Piano {index}"
                    },
                    "page_images": {"finance": ["data:image/png;base64," + "A" * 5000]},
                    "freshness": {},
                },
            )

    def test_archive_stops_after_page_and_reuses_small_summaries(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(archive, "DIRECTORY", Path(folder)),
        ):
            self.fixture_archive(Path(folder), 8)
            archive._entry_summary.cache_clear()
            with patch.object(archive, "load", wraps=archive.load) as load:
                first = archive.entries(limit=3)
                second = archive.entries(limit=3)
                self.assertEqual(load.call_count, 3)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 3)
            self.assertFalse(any("page_images" in row for row in first))
            self.assertFalse(
                set(row["id"] for row in first)
                & set(row["id"] for row in archive.entries(limit=3, offset=3))
            )

    def test_archive_cache_invalidates_replaced_files_and_search_pages_count_matches(
        self,
    ):
        with (
            TemporaryDirectory() as folder,
            patch.object(archive, "DIRECTORY", Path(folder)),
        ):
            self.fixture_archive(Path(folder), 8)
            all_matches = archive.entries(query="COFFEE")
            self.assertEqual(
                archive.entries(query="COFFEE", limit=2, offset=2), all_matches[2:4]
            )
            path = Path(folder) / (all_matches[0]["id"] + ".json")
            item = json.loads(path.read_text())
            item["pages"]["finance"] = "Changed merchant"
            write_json(path, item)
            self.assertNotIn(
                item["id"], [row["id"] for row in archive.entries(query="coffee")]
            )
            self.assertEqual(
                archive.entries(query="changed")[0]["matches"][0]["snippet"],
                "Changed merchant",
            )
            path.unlink()
            self.assertEqual(archive.entries(query="changed"), [])
            self.assertEqual(archive.entries(limit=0), [])

    def test_archive_route_paginates_without_fetching_external_data(self):
        from flask import Flask
        from web_control.private_tools import register

        app = Flask(__name__)
        app.secret_key = "test"
        register(app, lambda f: f, Mock(), ROOT, Mock())
        with (
            patch(
                "web_control.private_tools.render_template", return_value="ok"
            ) as render,
            patch.object(archive, "entries", return_value=[{}] * 51) as entries,
        ):
            response = app.test_client().get("/receipts?offset=50&q=coffee")
        self.assertEqual(response.status_code, 200)
        entries.assert_called_once_with(None, "coffee", limit=51, offset=50)
        self.assertEqual(len(render.call_args.kwargs["entries"]), 50)
        self.assertEqual(render.call_args.kwargs["previous_offset"], 0)
        self.assertEqual(render.call_args.kwargs["next_offset"], 100)

    def test_google_doc_helpers_share_urls_without_weakening_strict_ids(self):
        from services.google_docs import document_id, export_url

        identifier = "a" * 24
        self.assertEqual(
            document_id(
                "https://docs.google.com/document/d/" + identifier + "/edit?foo=bar"
            ),
            identifier,
        )
        self.assertEqual(document_id(identifier, strict=True), identifier)
        self.assertEqual(document_id("", allow_empty=True), "")
        with self.assertRaises(ValueError):
            document_id("bad", strict=True)
        self.assertEqual(
            export_url(identifier),
            "https://docs.google.com/document/d/" + identifier + "/export?format=txt",
        )

    def test_document_printer_import_does_not_load_live_collectors_or_credentials(self):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import print_google_doc; assert 'services.live_pipeline' not in sys.modules; assert print_google_doc.printer_safe_text('plain') == 'plain'",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
