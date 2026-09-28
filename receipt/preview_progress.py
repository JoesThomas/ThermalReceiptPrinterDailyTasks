"""Report completed receipt sections to the web preview worker."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATUS = Path(__file__).resolve().parent.parent / "data" / "live_preview_status.json"


def report(stage, completed, total):
    if os.environ.get("RECEIPT_LIVE_PREVIEW") != "1":
        return
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    try:
        started_at = json.loads(STATUS.read_text(encoding="utf-8")).get("started_at")
    except (OSError, ValueError):
        started_at = None
    payload = {"state": "running", "stage": stage, "completed": completed,
               "total": total, "updated_at": datetime.now(timezone.utc).isoformat()}
    if started_at:
        payload["started_at"] = started_at
    temporary = STATUS.with_name(f"{STATUS.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(STATUS)
