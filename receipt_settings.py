from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = PROJECT_ROOT / "data" / "receipt_settings.json"

DEFAULT_SETTINGS = {
    "features": {"calendar": True, "deliveries": True, "weather": True, "national_news": True, "local_news": True, "villa": True, "villa_trains": True},
    "one_shot": {"finance_check": False, "food_shop": False, "shopping_list": False},
    "display": {"weather_detail": "auto", "news_count": 3, "earlier_journeys": 3},
}

def _merge(defaults, supplied):
    result = deepcopy(defaults)
    if not isinstance(supplied, dict): return result
    for key, value in supplied.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        elif key in result:
            result[key] = value
    return result

def load_receipt_settings():
    if not SETTINGS_FILE.exists(): return deepcopy(DEFAULT_SETTINGS)
    try: raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return deepcopy(DEFAULT_SETTINGS)
    return _merge(DEFAULT_SETTINGS, raw)

def save_receipt_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    tmp.replace(SETTINGS_FILE)

def feature_enabled(settings, name, default=True): return bool(settings.get("features", {}).get(name, default))
def display_value(settings, name, default=None): return settings.get("display", {}).get(name, default)
def one_shot_requested(settings, name): return bool(settings.get("one_shot", {}).get(name, False))

def consume_one_shot(settings, name):
    one_shot = settings.setdefault("one_shot", {})
    if not one_shot.get(name, False): return False
    one_shot[name] = False
    save_receipt_settings(settings)
    return True

def google_doc_commands(todo_text):
    """Only complete Google Doc lines ending in '.' are treated as commands."""
    commands = set()
    for raw_line in (todo_text or "").splitlines():
        line = raw_line.strip()
        if not line.endswith("."): continue
        command = line[:-1].strip().lower()
        if command: commands.add(command)
    return commands

def command_requested(todo_text, *accepted):
    return bool(google_doc_commands(todo_text) & {x.strip().lower() for x in accepted})

def finance_requested(todo_text): return command_requested(todo_text, "finance", "finance check", "check finance")
def food_shop_requested(todo_text): return command_requested(todo_text, "food shop")
def shopping_list_requested(todo_text): return command_requested(todo_text, "shopping list")
