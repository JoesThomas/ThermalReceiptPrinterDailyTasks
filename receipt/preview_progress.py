"""Report completed receipt sections to the web preview worker."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATUS = Path(__file__).resolve().parent.parent / "data" / "live_preview_status.json"


def report(stage, completed, total):
    printing = os.environ.get("RECEIPT_FALLBACK_PREVIEW") == "1" or (os.environ.get("RECEIPT_WEB_CAPTURE") == "1" and os.environ.get("RECEIPT_LIVE_PREVIEW") != "1")
    if not printing and os.environ.get("RECEIPT_LIVE_PREVIEW") != "1":
        return
    status_file = STATUS.with_name("web_print_status.json") if printing else STATUS
    status_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        previous = json.loads(status_file.read_text(encoding="utf-8"))
        started_at = previous.get("started_at")
    except (OSError, ValueError):
        previous = {}
        started_at = None
    if printing:
        stage = stage.replace("preview", "receipt copy")
    payload = {**previous, "state": "running", "stage": stage, "completed": completed,
               "total": total, "updated_at": datetime.now(timezone.utc).isoformat()}
    if started_at:
        payload["started_at"] = started_at
    now = datetime.now(timezone.utc)
    timings = list(previous.get('timings', []))
    if previous.get('stage') != stage:
        try:
            began = datetime.fromisoformat(previous.get('stage_started_at', previous.get('updated_at', '')))
            seconds = max(0, (now - began).total_seconds())
            if previous.get('stage'):
                timings.append({'stage': previous['stage'], 'seconds': round(seconds, 2)})
        except (ValueError, TypeError):
            pass
        payload['stage_started_at'] = now.isoformat()
    payload['timings'] = timings[-80:]
    payload['stages'] = list(dict.fromkeys([*previous.get('stages', []), stage]))[-80:]
    from storage import write_json
    write_json(status_file, payload)
    from web_control.job_runtime import log_event
    log_event(os.environ.get("RECEIPT_JOB_ID", "preview"), stage)
    return
