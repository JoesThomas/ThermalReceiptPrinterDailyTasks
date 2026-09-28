"""Run a print job and persist a small, safe status for Receipt Control."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "web_print_status.json"
LOCK = ROOT / "data" / ".print_now.lock"


def save_status(state, page):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps({"state": state, "page": page,
                                     "updated_at": datetime.now(timezone.utc).isoformat()}),
                         encoding="utf-8")
    temporary.replace(STATUS)


def main():
    args = sys.argv[1:]
    page = args[1] if len(args) == 2 and args[0] == "--only" else "full receipt"
    # The parent writes the lock immediately after starting this process.
    # Wait for that write so a quick job cannot leave a stale lock behind.
    for _ in range(100):
        if LOCK.exists():
            break
        time.sleep(0.01)
    try:
        save_status("running", page)
        result = subprocess.run([sys.executable, str(ROOT / "main.py"), *args],
                                cwd=ROOT, check=False,
                                env={**os.environ, "RECEIPT_WEB_CAPTURE": "1"})
        save_status("completed" if result.returncode == 0 else "failed", page)
        return result.returncode
    except Exception:
        save_status("failed", page)
        raise
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
