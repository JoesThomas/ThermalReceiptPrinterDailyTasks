from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import json
from config import CACHE_DIR, FINANCE_CACHE_MINUTES

def _path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{name}.json"

def get(name: str, max_age_minutes: int = FINANCE_CACHE_MINUTES):
    path = _path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        saved = datetime.fromisoformat(data["saved_at"])
        if datetime.now() - saved > timedelta(minutes=max_age_minutes):
            return None
        return data.get("value")
    except Exception:
        return None

def put(name: str, value) -> None:
    _path(name).write_text(json.dumps({
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "value": value,
    }, indent=2), encoding="utf-8")
