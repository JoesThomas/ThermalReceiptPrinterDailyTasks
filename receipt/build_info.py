"""Local version and private configuration fingerprints for saved receipts."""

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def application_version():
    revision = os.environ.get("RECEIPT_APP_REVISION", "").strip()
    if (
        revision
        and len(revision) <= 80
        and all(c.isalnum() or c in "._-" for c in revision)
    ):
        return revision
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def finance_fingerprint():
    digest = hashlib.sha256()
    for name in (
        "finance_settings.json",
        "savings_goals.json",
        "savings.json",
        "investments.json",
        "subscriptions.json",
    ):
        digest.update(name.encode())
        try:
            with (ROOT / "data" / name).open("rb") as stream:
                content = stream.read(4_000_001)
            if len(content) > 4_000_000:
                return "unavailable"
            digest.update(content)
        except FileNotFoundError:
            digest.update(b"missing")
        except OSError:
            return "unavailable"
    return digest.hexdigest()


def metadata(values=None, *, finance=False):
    from receipt_settings import settings_state

    settings, warning = settings_state()
    from datetime import datetime, timezone

    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "finance_settings_fingerprint": finance_fingerprint() if finance else None,
        "application_version": application_version(),
        "receipt_settings_fingerprint": fingerprint(settings),
        "settings_recovered": warning is not None,
        "scenario_fingerprint": fingerprint(values) if values is not None else None,
    }
