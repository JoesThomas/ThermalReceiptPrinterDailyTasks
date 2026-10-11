from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import requests

from services.bank_session import retrieval, collect_snapshot
from services.bank_transport import refresh, get
from services.finance_source import FinanceDependencies
from services.observability import LOGGER, event
from finance import bank_accounts
from storage import read_json_object, write_json


class BankSessionTests(TestCase):
    def test_transactions_and_balances_share_authentication_and_inventory(self):
        with TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            stack.enter_context(
                patch.object(bank_accounts, "SELECTION", root / "selection.json")
            )
            stack.enter_context(
                patch.object(bank_accounts, "CATALOG", root / "catalog.json")
            )
            stack.enter_context(
                patch(
                    "finance.transaction_sources.load", return_value={"monzo": "first"}
                )
            )
            tokens = {p: "r-" + p for p in ("HSBC", "MONZO", "AMEX")}
            http = Mock()
            calls = []

            def post(url, **kwargs):
                p = kwargs["data"]["refresh_token"].removeprefix("r-")
                response = Mock()
                response.json.return_value = {
                    "access_token": "a-" + p,
                    "refresh_token": "r-" + p,
                }
                return response

            def read(url, **kwargs):
                p = kwargs["headers"]["Authorization"].removeprefix("Bearer a-")
                endpoint = url.removeprefix("https://bank.invalid")
                calls.append((p, endpoint))
                if endpoint in ("/accounts", "/cards"):
                    rows = [{"account_id": p + "-id", "display_name": p}]
                elif endpoint.endswith("/balance"):
                    rows = [{"current": 100, "available": 100, "currency": "GBP"}]
                else:
                    rows = []
                response = Mock()
                response.json.return_value = {"results": rows}
                return response

            http.post.side_effect = post
            http.get.side_effect = read

            def auth(p, ignored):
                return refresh(
                    p,
                    token_file=root / "tokens.json",
                    initial=lambda p: tokens[p],
                    load_tokens=lambda: dict(tokens),
                    save_tokens=lambda value: tokens.update(value),
                    client_id="private-client",
                    client_secret="private-secret",
                    auth_url="https://auth.invalid",
                    http=http,
                )

            def fetch(token, endpoint):
                return get(token, endpoint, data_url="https://bank.invalid", http=http)

            values = {
                name: (lambda *a, **kw: [])
                for name in FinanceDependencies.__dataclass_fields__
            }
            values.update(
                today=lambda: date(2026, 10, 11),
                FINANCE_TRANSACTION_LOOKBACK_DAYS=90,
                _initial_truelayer_refresh_token=lambda p: tokens[p],
                _refresh_truelayer_access_token=auth,
                _truelayer_account_ids=lambda token: [
                    r["account_id"] for r in fetch(token, "/accounts")["results"]
                ],
                _truelayer_card_ids=lambda token: [
                    r["account_id"] for r in fetch(token, "/cards")["results"]
                ],
                _dedupe_regular_payments=lambda rows: rows,
                _dedupe_subscriptions_against_regular=lambda *a: [],
                _monthlyised_spend=lambda *a, **kw: 0,
                _last_n_day_spend=lambda *a: 0,
                _incoming_total=lambda *a, **kw: 0,
                analyse_incoming_payments=lambda *a, **kw: ([], []),
                load_receipt_settings=lambda: {"finance": {}},
            )
            pipeline = SimpleNamespace(**values)
            pipeline.get_account_balances = lambda: bank_accounts.collect(
                auth, values["_initial_truelayer_refresh_token"], fetch
            )
            progress = []
            snapshot = collect_snapshot(
                pipeline, persist=False, progress=progress.append
            )
            self.assertEqual(http.post.call_count, 3)
            self.assertEqual(
                Counter(endpoint for p, endpoint in calls),
                Counter(
                    {
                        "/accounts": 2,
                        "/cards": 1,
                        "/accounts/HSBC-id/balance": 1,
                        "/accounts/MONZO-id/balance": 1,
                        "/cards/AMEX-id/balance": 1,
                    }
                ),
            )
            self.assertEqual(snapshot["data"][4]["bank_data_status"], "complete")
            self.assertEqual(snapshot["balances"]["HSBC"]["available"], 100)
            self.assertTrue(any("HSBC" in stage for stage in progress))
            # A subsequent session performs a new refresh; secrets never become a disk cache.
            with retrieval():
                auth("HSBC", None)
            self.assertEqual(http.post.call_count, 4)
            self.assertFalse((root / "tokens.json").exists())

    def test_token_rotation_is_serialized_across_concurrent_sessions(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "tokens.json"
            write_json(path, {"HSBC": "r0", "MONZO": "m0"})
            used = []
            barrier = Barrier(2)
            http = Mock()

            def post(url, **kwargs):
                used.append(kwargs["data"]["refresh_token"])
                response = Mock()
                response.json.return_value = {
                    "access_token": "access",
                    "refresh_token": f"r{len(used)}",
                }
                return response

            http.post.side_effect = post

            def collect(_):
                barrier.wait(timeout=3)
                with retrieval():
                    return refresh(
                        "HSBC",
                        token_file=path,
                        initial=lambda p: read_json_object(path)[p],
                        load_tokens=lambda: read_json_object(path),
                        save_tokens=lambda value: write_json(path, value),
                        client_id="client",
                        client_secret="secret",
                        auth_url="https://invalid.test",
                        http=http,
                    )

            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(
                    list(pool.map(collect, range(2))), ["access", "access"]
                )
            self.assertEqual(used, ["r0", "r1"])
            self.assertEqual(read_json_object(path), {"HSBC": "r2", "MONZO": "m0"})

    def test_failed_authentication_is_not_retried_in_same_session(self):
        with TemporaryDirectory() as folder:
            http = Mock()
            http.post.side_effect = requests.HTTPError("secret-token account-123")
            kwargs = dict(
                token_file=Path(folder) / "tokens.json",
                initial=lambda p: "secret-token",
                load_tokens=dict,
                save_tokens=lambda value: None,
                client_id="client",
                client_secret="secret",
                auth_url="https://invalid.test",
                http=http,
            )
            with retrieval(), self.assertLogs(LOGGER, level="WARNING") as logs:
                for _ in range(2):
                    with self.assertRaises(requests.HTTPError):
                        refresh("HSBC", **kwargs)
            self.assertEqual(http.post.call_count, 1)
            self.assertNotIn("secret-token", " ".join(logs.output))
            self.assertNotIn("account-123", " ".join(logs.output))

    def test_inventory_reuse_does_not_alias_and_balances_are_not_cached(self):
        http = Mock()
        response = Mock()
        response.json.return_value = {"results": [{"value": 1}]}
        http.get.return_value = response
        with retrieval():
            a = get("token", "/accounts", data_url="https://invalid.test", http=http)
            a["results"][0]["value"] = 9
            b = get("token", "/accounts", data_url="https://invalid.test", http=http)
            self.assertEqual(b["results"][0]["value"], 1)
            for _ in range(2):
                get(
                    "token",
                    "/accounts/id/balance",
                    data_url="https://invalid.test",
                    http=http,
                )
        self.assertEqual(http.get.call_count, 3)

    def test_deadline_stops_requests_and_events_omit_exception_text(self):
        with retrieval(timeout=-1):
            with self.assertRaises(TimeoutError):
                get("token", "/accounts", data_url="https://invalid.test", http=Mock())
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            event(
                "bank_read",
                provider="HSBC",
                status="failed",
                error=ValueError("secret payload"),
            )
        self.assertIn("ValueError", " ".join(logs.output))
        self.assertNotIn("secret payload", " ".join(logs.output))
