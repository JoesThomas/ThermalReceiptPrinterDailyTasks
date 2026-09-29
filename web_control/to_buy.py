"""Local wish list used by the optional To buy receipt section."""
from __future__ import annotations

import json
from pathlib import Path

TO_BUY_FILE = Path(__file__).resolve().parent.parent / "data" / "to_buy.json"
DEFAULT_ITEMS = ()


def load_to_buy():
    if not TO_BUY_FILE.exists():
        return list(DEFAULT_ITEMS)
    try:
        data = json.loads(TO_BUY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
            if all(isinstance(item, str) for item in items):
                return items
    except (OSError, ValueError):
        pass
    return list(DEFAULT_ITEMS)


def save_to_buy(text):
    items = [line.strip() for line in text.splitlines() if line.strip()]
    if len(items) > 100 or any(len(item) > 160 for item in items):
        raise ValueError("Use at most 100 items of 160 characters each.")
    TO_BUY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = TO_BUY_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(TO_BUY_FILE)
    return items
