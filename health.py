from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from config import FILES, PASSWORDS_FILE
from validation import validate_project

@dataclass
class HealthResult:
    name: str
    ok: bool
    detail: str = ""

def run_health_checks() -> list[HealthResult]:
    results = []
    results.append(HealthResult("passwords.json", PASSWORDS_FILE.exists(),
                                "present" if PASSWORDS_FILE.exists() else "missing"))
    errors = validate_project(FILES)
    results.append(HealthResult("meal data", not errors,
                                "OK" if not errors else f"{len(errors)} validation issue(s)"))
    return results
