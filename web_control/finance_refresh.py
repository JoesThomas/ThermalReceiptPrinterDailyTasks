"""Private bank snapshots and one background refresh per installation."""

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from zoneinfo import ZoneInfo
from storage import PrivateStore, file_lock, read_json_object, write_json
from services.observability import event

MAX_AGE_SECONDS = 30 * 60
MAX_SECONDS = 600


def encode(value):
    if isinstance(value, (datetime, date, Decimal)):
        return {"__receipt_type": type(value).__name__, "value": str(value)}
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {"__receipt_type", "value"}:
            converters = {
                "date": date.fromisoformat,
                "datetime": datetime.fromisoformat,
                "Decimal": Decimal,
            }
            if value["__receipt_type"] in converters:
                return converters[value["__receipt_type"]](value["value"])
        return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value


class FinanceRefresh:
    def __init__(self, root, collect=None, *, on_success=None):
        self.root = Path(root)
        self.directory = self.root / "cache" / "finance_review"
        self.snapshot_file = self.directory / "snapshot.json"
        self.status_file = self.directory / "status.json"
        self.guard = Lock()
        self.worker = None
        self.collect = collect or self._collect
        self.on_success = on_success

    def scope(self):
        # Invalidate only bank-source choices, not local forecast/display settings.
        digest = hashlib.sha256(b"cash-excludes-overdraft-v1")
        for name in ("bank_account_selection.json", "transaction_sources.json", "bank_overdrafts.json"):
            path = self.root / "data" / name
            try:
                digest.update(path.read_bytes())
            except FileNotFoundError:
                digest.update(b"absent")
        return digest.hexdigest()

    def read(self):
        try:
            value = PrivateStore(
                self.snapshot_file, default=dict, max_bytes=20_000_000
            ).read()
            if value.get("version") != 1 or value.get("scope") != self.scope():
                return None
            stamp = datetime.fromisoformat(value["checked_at"])
            if stamp.tzinfo is None:
                return None
            snapshot = decode(value)
            if (
                not isinstance(snapshot.get("data"), list)
                or len(snapshot["data"]) != 5
                or not isinstance(snapshot.get("balances"), dict)
                or not isinstance(snapshot["data"][4], dict)
                or any(not isinstance(rows, list) for rows in snapshot["data"][:4])
            ):
                return None
            return snapshot
        except (ValueError, OSError, TypeError, KeyError):
            return None

    def status(self):
        value = read_json_object(self.status_file)
        # A stopped/restarted server must not leave an endless running indication.
        try:
            if (
                value.get("state") == "running"
                and (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(value["started_at"])
                ).total_seconds()
                > MAX_SECONDS + 30
            ):
                value = {
                    **value,
                    "state": "failed",
                    "stage": "Refresh stopped before completion. Try again.",
                }
        except (KeyError, ValueError, TypeError):
            value = {}
        return value or {
            "state": "idle",
            "stage": "Bank data has not been retrieved yet.",
        }

    def fresh(self, snapshot, status=None):
        if not snapshot:
            return False
        try:
            stamp = datetime.fromisoformat(snapshot["checked_at"])
            now = datetime.now(timezone.utc)
            age = (now - stamp).total_seconds()
            same_day = (
                stamp.astimezone(ZoneInfo("Europe/London")).date()
                == now.astimezone(ZoneInfo("Europe/London")).date()
            )
            return (
                same_day
                and 0 <= age <= MAX_AGE_SECONDS
                and (status or self.status()).get("state") != "failed"
            )
        except (ValueError, TypeError, KeyError):
            return False

    def start(self, *, force=False):
        with self.guard:
            if self.worker and self.worker.is_alive():
                return False
            status = self.status()
            if not force and status.get("state") == "failed":
                try:
                    if (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(status["updated_at"])
                    ).total_seconds() < 60:
                        return False
                except (KeyError, ValueError, TypeError):
                    pass
            ready = Event()
            self.worker = Thread(
                target=self._run, args=(ready,), daemon=True, name="finance-refresh"
            )
            self.worker.start()
        ready.wait(
            0.1
        )  # Only wait for local status creation; never for a bank request.
        return True

    def _run(self, ready):
        started = monotonic()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            os.chmod(self.directory, 0o700)
            # Another web process may already be doing this same refresh.
            with file_lock(self.directory / "refresh.json", blocking=False):
                scope = self.scope()
                previous = self.read()
                state = {
                    "state": "running",
                    "stage": "Connecting to banks",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "timings": [],
                    "scope": scope,
                    "checked_at": previous["checked_at"] if previous else None,
                }
                last = monotonic()

                def progress(message):
                    nonlocal last
                    if monotonic() - started > MAX_SECONDS:
                        raise TimeoutError("Finance refresh time limit reached")
                    if state["stage"] != message:
                        state["timings"] = (
                            state["timings"]
                            + [
                                {
                                    "stage": state["stage"],
                                    "seconds": round(monotonic() - last, 2),
                                }
                            ]
                        )[-20:]
                        last = monotonic()
                    state.update(
                        stage=message, updated_at=datetime.now(timezone.utc).isoformat()
                    )
                    write_json(self.status_file, state)

                progress("Connecting to banks")
                ready.set()
                try:
                    snapshot = self.collect(progress)
                    if snapshot["data"][4].get("bank_data_status") not in {
                        "complete",
                        "partial",
                    }:
                        raise ValueError("No transaction source succeeded")
                    if scope != self.scope():
                        raise ValueError("Bank source choices changed during refresh")
                    snapshot = {
                        **snapshot,
                        "version": 1,
                        "scope": scope,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    }
                    encoded = encode(snapshot)
                    if len(json.dumps(encoded).encode()) > 20_000_000:
                        raise ValueError("Bank snapshot size limit reached")
                    from finance.amex_interest import capture as capture_interest
                    capture_interest(snapshot['data'][0], path=self.root / 'data' / 'amex_interest_alerts.json')
                    from finance.amex_protection import capture as capture_protection
                    capture_protection(snapshot['balances'], snapshot['data'][0], snapshot['data'][4], path=self.root / 'data' / 'amex_payment_protection.json', checked_at=snapshot['checked_at'])
                    write_json(self.snapshot_file, encoded)
                    progress("Bank data retrieved; preparing the review")
                    if self.on_success:
                        try:
                            self.on_success(snapshot)
                        except Exception as error:
                            event('finance_observation', status='failed', error=error)
                            progress('Bank data retrieved; finance history could not be updated.')
                    state.update(
                        state="completed",
                        checked_at=snapshot["checked_at"],
                        coverage=snapshot["data"][4].get("bank_data_status"),
                        seconds=round(monotonic() - started, 2),
                    )
                    write_json(self.status_file, state)
                except Exception as error:
                    from finance.amex_protection import mark_failed
                    try:
                        mark_failed(path=self.root / 'data' / 'amex_payment_protection.json')
                    except (ValueError, OSError):
                        pass  # Preserve damaged private state for repair.
                    event(
                        "finance_refresh",
                        status="failed",
                        seconds=monotonic() - started,
                        error=error,
                    )
                    state.update(
                        state="failed",
                        stage="Bank refresh unavailable. Previous data is retained; try again.",
                        updated_at=datetime.now(timezone.utc).isoformat(),
                    )
                    write_json(self.status_file, state)
        except BlockingIOError:
            pass  # Existing installation worker owns status and snapshot files.
        except Exception as error:
            event("finance_worker", status="failed", error=error)
        finally:
            ready.set()

    @staticmethod
    def _collect(progress):
        from services import live_pipeline as pipeline
        from services.bank_session import collect_snapshot

        return collect_snapshot(pipeline, progress=progress)

    def public_status(self):
        # Polling reads only the small status file, never the transaction payload.
        status = deepcopy(self.status())
        stamp = (
            status.get("checked_at")
            if status.pop("scope", None) == self.scope()
            else None
        )
        try:
            if stamp and datetime.fromisoformat(stamp).tzinfo is None:
                stamp = None
        except (ValueError, TypeError):
            stamp = None
        status.update(
            checked_at=stamp,
            fresh=self.fresh({"checked_at": stamp}, status) if stamp else False,
        )
        return status
