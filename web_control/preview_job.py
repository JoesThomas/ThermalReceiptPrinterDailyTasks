"""Fetch a live receipt in a separate process, without touching the printer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "live_preview_status.json"
LOCK = ROOT / "data" / ".live_preview.lock"


def save_status(state):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_name(f"{STATUS.name}.{os.getpid()}.tmp")
    now = datetime.now(timezone.utc).isoformat()
    previous = {}
    try:
        previous = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    temporary.write_text(json.dumps({"state": state, "stage": "Starting receipt" if state == "running" else state,
                                     "completed": 0 if state == "running" else previous.get("completed", 0),
                                     "total": 5, "started_at": now if state == "running" else previous.get("started_at", now),
                                     "updated_at": now}),
                         encoding="utf-8")
    temporary.replace(STATUS)


def main():
    for _ in range(100):
        if LOCK.exists():
            break
        time.sleep(0.01)
    try:
        save_status("running")
        args = ["--finance"] if sys.argv[1:] == ["--finance"] else []
        result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--live-preview", *args],
                                cwd=ROOT, check=False,
                                env={**os.environ, "RECEIPT_LIVE_PREVIEW": "1"})
        save_status("completed" if result.returncode == 0 else "failed")
        return result.returncode
    except Exception:
        save_status("failed")
        raise
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
