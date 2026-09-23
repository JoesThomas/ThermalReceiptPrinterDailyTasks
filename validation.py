from __future__ import annotations
import json
from pathlib import Path
from typing import Any

class ValidationError(RuntimeError):
    pass

def load_json(path: Path, expected_type: type | tuple[type, ...] | None = None) -> Any:
    if not path.exists():
        raise ValidationError(f"Missing JSON file: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {path.name}: {exc}") from exc
    if expected_type is not None and not isinstance(value, expected_type):
        raise ValidationError(
            f"{path.name}: expected {expected_type}, found {type(value).__name__}"
        )
    return value

def require_keys(obj: dict, keys: tuple[str, ...], context: str) -> list[str]:
    return [f"{context}: missing '{key}'" for key in keys if key not in obj]

def validate_recipe(recipe: dict, index: int) -> list[str]:
    errors = []
    context = f"recipe[{index}] {recipe.get('name', recipe.get('id', '<unnamed>'))}"
    errors += require_keys(recipe, ("name", "ingredients", "method"), context)
    if "ingredients" in recipe and not isinstance(recipe["ingredients"], list):
        errors.append(f"{context}: ingredients must be a list")
    if "method" in recipe and not isinstance(recipe["method"], list):
        errors.append(f"{context}: method must be a list")
    vague = (
        "cook the vegetables",
        "cook until done",
        "prepare the sauce",
        "add the sauce",
        "cook until ready",
    )
    for step in recipe.get("method", []):
        low = str(step).lower()
        if any(term in low for term in vague):
            errors.append(f"{context}: vague method step -> {step}")
    return errors

def validate_project(files: dict[str, Path]) -> list[str]:
    errors = []
    for key, path in files.items():
        try:
            value = load_json(path)
            if key == "recipes":
                recipes = value.get("recipes", value) if isinstance(value, dict) else value
                if not isinstance(recipes, list):
                    errors.append("recipes.json: expected recipe list or {'recipes': [...]}")
                else:
                    for i, recipe in enumerate(recipes):
                        if not isinstance(recipe, dict):
                            errors.append(f"recipe[{i}]: expected object")
                        else:
                            errors.extend(validate_recipe(recipe, i))
        except ValidationError as exc:
            errors.append(str(exc))
    return errors
