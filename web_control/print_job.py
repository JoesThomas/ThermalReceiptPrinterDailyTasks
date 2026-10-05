"""Run a print job and persist a small, safe status for Receipt Control."""
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
STATUS = ROOT / "data" / "web_print_status.json"
LOCK = ROOT / "data" / ".print_now.lock"
sys.path.insert(0, str(ROOT))
from web_control.job_runtime import run_bounded, JobCancelled, log_event, MAX_SECONDS


def save_status(state, page):
    from web_control.job_status import save
    return save(STATUS, state, page=page)


def main():
    args = sys.argv[1:]
    scheduled = bool(args and args[0] == '--scheduled')
    if scheduled:
        args = args[1:]
    page = " + ".join(args[1:]) if args and args[0] == "--pages" else args[1] if len(args) == 2 and args[0] == "--only" else "full receipt"
    # The parent writes the lock immediately after starting this process.
    # Wait for that write so a quick job cannot leave a stale lock behind.
    for _ in range(100):
        if LOCK.exists():
            break
        time.sleep(0.01)
    try:
        save_status("running", page)
        job_id = json.loads(STATUS.read_text())['job_id']
        log_event(job_id, 'print started')
        command = [sys.executable, str(ROOT / "main.py"), *args]
        if args == ['--printer-test']:
            command = [sys.executable, str(ROOT / 'web_control' / 'printer_test_job.py')]
        if args and args[0] == '--archive':
            if len(args) != 3:
                raise ValueError('Invalid archive command')
            command = [sys.executable, str(ROOT / 'web_control' / 'archive_job.py'), *args[1:]]
        if scheduled:
            from receipt.printer import readiness
            reachable, _ = readiness()
            if reachable is False:
                log_event(job_id, 'printer unreachable; generating saved preview')
                code = run_bounded([sys.executable, str(ROOT / 'main.py'), '--live-preview', *args],
                                   cwd=ROOT, env={**os.environ, 'RECEIPT_JOB_ID': job_id, 'RECEIPT_FALLBACK_PREVIEW': '1'})
                save_status('failed', page)
                from storage import write_json
                payload = json.loads(STATUS.read_text())
                payload['stage'] = ('Printer unreachable; live preview saved. Open Receipt to view it.' if code == 0
                                    else 'Printer unreachable; preview generation also failed. Check the job log.')
                payload['preview_saved'] = code == 0
                write_json(STATUS, payload)
                log_event(job_id, 'scheduled print skipped; no automatic print retry')
                return 1
        code = run_bounded(command, cwd=ROOT,
                           env={**os.environ, "RECEIPT_WEB_CAPTURE": "1", 'RECEIPT_JOB_ID': job_id})
        save_status("completed" if code == 0 else "failed", page)
        log_event(job_id, f'print ended exit={code}')
        return code
    except subprocess.TimeoutExpired:
        save_status('timed_out', page)
        log_event(job_id, 'print timed out; child stopped')
        return 124
    except JobCancelled:
        save_status('cancelled', page)
        log_event(job_id, 'print cancelled; child stopped')
        return 130
    except Exception:
        save_status("failed", page)
        raise
    finally:
        from web_control.job_runtime import release_owned_lock
        release_owned_lock(LOCK)


if __name__ == "__main__":
    raise SystemExit(main())
