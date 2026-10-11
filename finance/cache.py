from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import json
import re
from config import CACHE_DIR, FINANCE_CACHE_MINUTES

def _path(name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
        raise ValueError("Use a simple cache name.")
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
    from storage import write_json
    write_json(_path(name), {'saved_at': datetime.now().isoformat(timespec='seconds'), 'value': value})
