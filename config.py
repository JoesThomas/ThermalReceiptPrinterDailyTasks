from __future__ import annotations
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
CACHE_DIR = BASE_DIR / "cache"
MEAL_PLAN_DIR = BASE_DIR / "meal_plans"
PASSWORDS_FILE = BASE_DIR / "passwords.json"

TIMEZONE_NAME = "Europe/London"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
RECEIPT_WIDTH = 42

FEATURES = {
    "weather": True,
    "news": True,
    "calendar": True,
    "deliveries": True,
    "meals": True,
    "football": True,
    "finance": True,
}

PRINTING = {
    "cut_after_information": True,
    "cut_after_actions": True,
    "cut_after_food": True,
    "finance_own_receipt": True,
}

FILES = {
    "recipes": DATA_DIR / "recipes.json",
    "components": DATA_DIR / "components.json",
    "equipment": DATA_DIR / "equipment.json",
    "cooking_rules": DATA_DIR / "cooking_rules.json",
    "meal_preferences": DATA_DIR / "meal_preferences.json",
    "pantry": DATA_DIR / "pantry.json",
    "freezer": DATA_DIR / "freezer.json",
    "recipe_history": DATA_DIR / "recipe_history.json",
    "meal_overrides": DATA_DIR / "meal_overrides.json",
    "finance_categories": DATA_DIR / "finance_categories.json",
    "finance_history": DATA_DIR / "finance_history.json",
    "savings": DATA_DIR / "savings.json",
}

FINANCE_CACHE_MINUTES = 30
DELIVERY_LOOKAHEAD_DAYS = 14
MAX_RECEIPT_LINES = {
    "information": 180,
    "actions": 180,
    "food": 260,
    "finance": 260,
}


TRAVEL = {
    "drive_buffer_minutes": 10,
    "public_transport_buffer_minutes": 15,
    "walk_buffer_minutes": 10,
    "show_walk_under_minutes": 25,
    "chain_from_previous_event": True,
}

FINANCE_TRENDS = {
    "minimum_category_spend": 20.0,
    "current_days": 30,
    "baseline_days": 90,
}
