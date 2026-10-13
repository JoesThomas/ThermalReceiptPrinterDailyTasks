from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path
from receipt.location_settings import DEFAULT_LOCATION

PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = PROJECT_ROOT / "data" / "receipt_settings.json"

DEFAULT_SETTINGS = {
    "private_backup": {"enabled": True, "keep": 14},
    "api_health": {"enabled": True, "interval_minutes": 60},
    "layout": {
        "order": ["information", "actions", "food", "finance"],
        "detail": "detailed",
    },
    "print_schedule": {"enabled": True, "time": "03:00"},
    "location": DEFAULT_LOCATION,
    "features": {
        "calendar": True,
        "meals": True,
        "deliveries": True,
        "weather": True,
        "national_news": True,
        "local_news": True,
        "sport_news": True,
        "villa": True,
        "villa_trains": True,
    },
    "one_shot": {
        "finance_check": False,
        "food_shop": False,
        "shopping_list": False,
        "to_buy": False,
        "future_tasks": False,
    },
    "display": {"weather_detail": "full", "news_count": 3, "sport_count": 3},
    "therapy_payment": {"payee": "", "provider": "MONZO"},
    "finance": {"salary_payee": ""},
}


def _merge(defaults, supplied):
    result = deepcopy(defaults)
    if not isinstance(supplied, dict):
        return result
    for key, value in supplied.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        elif key in result:
            result[key] = value
    return result


def validate_settings(raw):
    """Accept legacy partial objects, but reject wrong types and unsafe values."""
    from receipt.layout import validate as validate_layout
    from receipt.location_settings import validate_location
    from storage import validate_schema_version
    import re

    if not isinstance(raw, dict):
        raise ValueError("Receipt settings must be an object.")
    validate_schema_version(raw, 1)
    for section, defaults in DEFAULT_SETTINGS.items():
        if section not in raw:
            continue
        supplied = raw[section]
        if not isinstance(supplied, dict):
            raise ValueError(f"Invalid {section} settings.")
        for key, value in supplied.items():
            if key not in defaults or section == "location":
                continue
            expected = type(defaults[key])
            if type(value) is not expected:
                raise ValueError(f"Invalid {section} {key}.")
    settings = _merge(DEFAULT_SETTINGS, raw)
    validate_location(settings["location"])
    validate_layout(settings["layout"])
    if not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", settings["print_schedule"]["time"]
    ):
        raise ValueError("Invalid daily print time.")
    if settings["private_backup"]["keep"] not in (7, 14, 30):
        raise ValueError("Invalid backup retention.")
    if settings["api_health"]["interval_minutes"] not in (15, 30, 60, 180, 360, 1440):
        raise ValueError("Invalid integration check interval.")
    if (
        not 1 <= settings["display"]["news_count"] <= 10
        or not 1 <= settings["display"]["sport_count"] <= 5
    ):
        raise ValueError("Invalid headline count.")
    if settings["display"]["weather_detail"] not in (
        "full",
        "compact",
        "brief",
        "hourly",
        "summary",
    ):
        raise ValueError("Invalid weather detail.")
    if settings["therapy_payment"]["provider"] not in ("MONZO", "HSBC"):
        raise ValueError("Invalid therapy payment provider.")


def settings_diagnosis(raw):
    """Return a safe validator reason, never a supplied value or traceback."""
    allowed = {
        "Receipt settings must be an object.", "Unsupported private schema version",
        "Choose compact or detailed receipts.", "Choose each receipt page once.",
        "Invalid daily print time.", "Invalid backup retention.",
        "Invalid integration check interval.", "Invalid headline count.",
        "Invalid weather detail.", "Invalid therapy payment provider.",
        "Enter a valid latitude.", "Enter a valid longitude.",
        "Use a BBC local RSS URL from feeds.bbci.co.uk/news/.",
    }
    for section, defaults in DEFAULT_SETTINGS.items():
        allowed.add(f"Invalid {section} settings.")
        allowed.update(f"Invalid {section} {key}." for key in defaults)
    for key, maximum in (("name", 18), ("region", 19), ("local_news_label", 35)):
        allowed.add(f"Enter a valid {key.replace('_', ' ')} (up to {maximum} characters).")
    try:
        validate_settings(raw)
    except ValueError as error:
        return str(error) if str(error) in allowed else "Receipt settings failed validation."
    except (TypeError, ArithmeticError):
        return "Receipt settings contain an unsupported value type."
    return None


def _store(path):
    from storage import PrivateStore

    return PrivateStore(
        path,
        default=lambda: deepcopy(DEFAULT_SETTINGS),
        validate=validate_settings,
        max_bytes=1_000_000,
        schema_version=1,
        migrations={0: lambda value: value},
    )


def last_good_file():
    return SETTINGS_FILE.with_name(SETTINGS_FILE.stem + ".last-good.json")


def settings_state():
    """Read-only recovery: never overwrite a damaged or newer settings file."""
    try:
        raw = _store(SETTINGS_FILE).read()
        return _merge(DEFAULT_SETTINGS, raw), None
    except (OSError, ValueError):
        try:
            if not last_good_file().exists():
                raise ValueError()
            settings = _merge(DEFAULT_SETTINGS, _store(last_good_file()).read())
            message = (
                "Receipt settings could not be read. Using the last working settings."
            )
        except (OSError, ValueError):
            settings = deepcopy(DEFAULT_SETTINGS)
            message = "Receipt settings could not be read and no working copy is available. Review the settings before saving."
        settings["print_schedule"]["enabled"] = False
        settings["one_shot"] = {key: False for key in settings["one_shot"]}
        return (
            settings,
            message
            + " Automatic printing is paused until valid settings are saved. The original file is preserved.",
        )


def load_receipt_settings():
    return settings_state()[0]


def save_receipt_settings(settings):
    from datetime import datetime, timezone
    from uuid import uuid4
    from storage import file_lock, write_bytes, write_json

    validate_settings(settings)
    value = dict(_merge(DEFAULT_SETTINGS, settings), schema_version=1)
    with file_lock(SETTINGS_FILE):
        if SETTINGS_FILE.exists():
            # An older application must not downgrade newer settings.
            try:
                from storage import validate_schema_version

                raw = json.loads(SETTINGS_FILE.read_text())
                if (
                    isinstance(raw, dict)
                    and type(raw.get("schema_version", 0)) is int
                    and raw.get("schema_version", 0) > 1
                ):
                    validate_schema_version(raw, 1)
            except (OSError, json.JSONDecodeError):
                pass
            try:
                _store(SETTINGS_FILE).read()
            except (OSError, ValueError):
                preserved = SETTINGS_FILE.with_name(
                    SETTINGS_FILE.stem
                    + ".invalid-"
                    + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    + "-"
                    + uuid4().hex[:8]
                    + ".json"
                )
                write_bytes(preserved, SETTINGS_FILE.read_bytes())
        write_json(SETTINGS_FILE, value)
        write_json(last_good_file(), value)


def repair_weather_detail():
    """Repair the legacy weather value only, retaining every other stored key."""
    from datetime import datetime, timezone
    from uuid import uuid4
    from storage import file_lock, write_bytes, write_json

    with file_lock(SETTINGS_FILE):
        with SETTINGS_FILE.open('rb') as stream:
            original = stream.read(1_000_001)
        if len(original) > 1_000_000:
            raise ValueError('Receipt settings exceed the supported size limit.')
        raw = json.loads(original)
        if not isinstance(raw, dict) or not isinstance(raw.get('display'), dict):
            raise ValueError('Review the display settings before repairing weather detail.')
        candidate = deepcopy(raw)
        candidate['display']['weather_detail'] = 'full'
        validate_settings(candidate)  # Reject other errors and newer schemas before writing.
        if raw['display'].get('weather_detail') == 'full':
            return None
        preserved = SETTINGS_FILE.with_name(SETTINGS_FILE.stem+'.invalid-'
                    +datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]+'.json')
        write_bytes(preserved, original)
        write_json(SETTINGS_FILE, candidate)
        return preserved


def feature_enabled(settings, name, default=True):
    return bool(settings.get("features", {}).get(name, default))


def display_value(settings, name, default=None):
    return settings.get("display", {}).get(name, default)


def one_shot_requested(settings, name):
    return bool(settings.get("one_shot", {}).get(name, False))


def consume_one_shot(settings, name):
    one_shot = settings.setdefault("one_shot", {})
    if not one_shot.get(name, False):
        return False
    one_shot[name] = False
    save_receipt_settings(settings)
    return True


def google_doc_commands(todo_text):
    """Only complete Google Doc lines ending in '.' are treated as commands."""
    commands = set()
    for raw_line in (todo_text or "").splitlines():
        line = raw_line.strip()
        if not line.endswith("."):
            continue
        command = line[:-1].strip().lower()
        if command:
            commands.add(command)
    return commands


def command_requested(todo_text, *accepted):
    return bool(google_doc_commands(todo_text) & {x.strip().lower() for x in accepted})


def finance_requested(todo_text):
    return command_requested(todo_text, "finance", "finance check", "check finance")


def food_shop_requested(todo_text):
    return command_requested(todo_text, "food shop")


def shopping_list_requested(todo_text):
    return command_requested(todo_text, "shopping list")
