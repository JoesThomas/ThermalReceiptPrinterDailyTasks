"""Fetch a live receipt in a separate process, without touching the printer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "live_preview_status.json"
LOCK = ROOT / "data" / ".live_preview.lock"
sys.path.insert(0, str(ROOT))
from web_control.job_runtime import run_bounded, JobCancelled, log_event, MAX_SECONDS


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
                                     "job_id": uuid.uuid4().hex[:12] if state == "running" else previous.get("job_id"),
                                     "timeout_seconds": MAX_SECONDS, "total": 5, "started_at": now if state == "running" else previous.get("started_at", now),
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
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--finance', action='store_true')
        parser.add_argument('--only', choices=['information', 'actions', 'food', 'finance'])
        parser.add_argument('--pages', nargs='+', choices=['information','actions','food','finance'])
        options = parser.parse_args()
        args = ['--finance'] if options.finance or options.only == 'finance' else []
        if options.pages:
            from receipt.selection import validate
            validate(options.pages)
            args += ['--pages', *options.pages]
        elif options.only:
            args += ['--only', options.only]
        job_id = json.loads(STATUS.read_text())['job_id']
        log_event(job_id, 'preview started')
        code = run_bounded([sys.executable, str(ROOT / "main.py"), "--live-preview", *args],
                                cwd=ROOT,
                                env={**os.environ, "RECEIPT_LIVE_PREVIEW": "1", "RECEIPT_JOB_ID": job_id})
        save_status("completed" if code == 0 else "failed")
        log_event(job_id, f'preview ended exit={code}')
        return code
    except subprocess.TimeoutExpired:
        save_status('timed_out')
        log_event(job_id, 'preview timed out; child stopped')
        return 124
    except JobCancelled:
        save_status('cancelled')
        log_event(job_id, 'preview cancelled; child stopped')
        return 130
    except Exception:
        save_status("failed")
        raise
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
