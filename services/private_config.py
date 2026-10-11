"""Load private settings without importing live collectors or printer clients."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path=None):
    path = Path(path) if path is not None else ROOT / "passwords.json"
    if not path.exists():
        raise RuntimeError(f"Missing private configuration file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("passwords.json must contain a JSON object.")
    return value


def value(config, section, key, default=""):
    section_data = config.get(section, {})
    return section_data.get(key, default) if isinstance(section_data, dict) else default
