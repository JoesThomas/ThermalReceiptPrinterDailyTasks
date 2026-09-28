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
    payload = {"state": "running", "stage": stage, "completed": completed,
               "total": total, "updated_at": datetime.now(timezone.utc).isoformat()}
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(STATUS)
