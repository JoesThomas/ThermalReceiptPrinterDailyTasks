"""Small, file-backed controls shared by the receipt and web interface."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FOOD_SHOP_FILE = ROOT / "data" / "food_shop_override.json"
TESCO_PROGRESS_FILE = ROOT / "data" / "tesco_progress.json"
MEALS_EATEN_FILE = ROOT / "data" / "meals_eaten.json"


def _read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def food_shop_override():
    if not FOOD_SHOP_FILE.exists():
        return None
    value = _read(FOOD_SHOP_FILE, {})
    return value.get("items", []) if isinstance(value, dict) else None


def save_food_shop(text):
    items = [line.strip() for line in text.splitlines() if line.strip()]
    if len(items) > 150 or any(len(item) > 180 for item in items):
        raise ValueError("Use at most 150 items of 180 characters each.")
    _write(FOOD_SHOP_FILE, {"items": items})
    return items


def tesco_progress(items):
    data = _read(TESCO_PROGRESS_FILE, {})
    week = datetime.now(ZoneInfo("Europe/London")).date().isocalendar()
    key = f"{week.year}-{week.week:02d}"
    progress = data.get("items", {}) if isinstance(data, dict) and data.get("week") == key else {}
    return {item: bool(progress.get(item)) for item in items}


def mark_tesco_item(item, items, added):
    if item not in items:
        raise ValueError("Item is not on the current shopping list.")
    progress = tesco_progress(items)
    progress[item] = bool(added)
    week = datetime.now(ZoneInfo("Europe/London")).date().isocalendar()
    _write(TESCO_PROGRESS_FILE, {"week": f"{week.year}-{week.week:02d}", "items": progress})


def meal_confirmation(day):
    data = _read(MEALS_EATEN_FILE, {})
    return data.get(day.isoformat()) if isinstance(data, dict) else None


def clear_meal_confirmation(day):
    data = _read(MEALS_EATEN_FILE, {})
    if isinstance(data, dict):
        data.pop(day.isoformat(), None)
        _write(MEALS_EATEN_FILE, data)


def confirm_meal(day, recipe_name, valid_names):
    if recipe_name not in valid_names or day > datetime.now(ZoneInfo("Europe/London")).date():
        raise ValueError("Choose a recipe and a date up to today.")
    data = _read(MEALS_EATEN_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data[day.isoformat()] = {"recipe": recipe_name,
                             "confirmed_at": datetime.now(ZoneInfo("Europe/London")).isoformat(timespec="seconds")}
    _write(MEALS_EATEN_FILE, data)


def map_embed_url(location):
    location = location.strip()
    return ("https://www.google.com/maps?q=" + quote_plus(location) + "&output=embed") if location else None


def map_link_url(location):
    location = location.strip()
    return ("https://www.google.com/maps/search/?api=1&query=" + quote_plus(location)) if location else None
