from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import json
from validation import load_json

@dataclass
class StockItem:
    name: str
    quantity: float
    unit: str
    location: str = "pantry"
    opened: bool = False
    bought: str | None = None
    use_by: str | None = None
    batch_id: str | None = None

def use_first(items: list[dict], today: date | None = None, days: int = 3) -> list[dict]:
    today = today or date.today()
    urgent = []
    for item in items:
        raw = item.get("use_by")
        if not raw:
            continue
        try:
            expiry = datetime.fromisoformat(raw).date()
        except ValueError:
            continue
        remaining = (expiry - today).days
        if remaining <= days:
            urgent.append({**item, "days_remaining": remaining})
    return sorted(urgent, key=lambda x: x["days_remaining"])

def consume(items: list[dict], name: str, amount: float, unit: str) -> list[dict]:
    for item in items:
        if item.get("name", "").lower() == name.lower() and item.get("unit") == unit:
            item["quantity"] = max(0, float(item.get("quantity", 0)) - amount)
            break
    return items

def add_batch(items: list[dict], recipe_id: str, portions: float, location: str, cooked: date) -> list[dict]:
    items.append({
        "name": recipe_id.replace("_", " ").title(),
        "recipe": recipe_id,
        "portions": portions,
        "location": location,
        "cooked": cooked.isoformat(),
        "batch_id": f"{recipe_id}-{cooked.isoformat()}",
    })
    return items

def save_json(path: Path, value) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)
