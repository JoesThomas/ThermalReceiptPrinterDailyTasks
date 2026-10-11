from __future__ import annotations
import math
from config import DATA_DIR
from validation import load_json

def choose_pack_size(item_name: str, required: float, already_have: float = 0) -> dict:
    need = max(0, required - already_have)
    db = load_json(DATA_DIR / "pack_sizes.json", dict)
    info = db.get(item_name.lower())
    if not info or need <= 0:
        return {"required": required, "have": already_have, "need": need, "buy": need, "remaining": 0}
    packs = sorted(float(x) for x in info.get("packs", []))
    buy = next((x for x in packs if x >= need), None)
    if buy is None and packs:
        buy = math.ceil(need / packs[-1]) * packs[-1]
    buy = buy or need
    return {
        "required": required,
        "have": already_have,
        "need": need,
        "buy": buy,
        "remaining": max(0, already_have + buy - required),
        "unit": info.get("unit", ""),
    }
