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
    from receipt_settings import load_receipt_settings
    from services.source_cache import timings
    from receipt.local_time import uk_now
    from web_control.scheduled_print import next_print_time
    try:
        settings = load_receipt_settings()
        due = next_print_time(uk_now(), settings)
        results.append(HealthResult("receipt settings", True,
                                    "schedule disabled" if due is None else "next print " + due.strftime("%d %b %H:%M %Z")))
    except (ValueError, TypeError, OSError):
        results.append(HealthResult("receipt settings", False, "settings could not be validated"))
    for row in timings():
        status = row.get('status', 'unavailable')
        results.append(HealthResult(row['name'], status in {'checked', 'cached'},
                                    status + " · last successful check " + str(row.get('source_checked_at') or 'none')))
    required = ['web_control/templates/navigation.html', 'web_control/static/control.js',
                'web_control/static/control.css', 'finance/tax_rules.json']
    root = Path(__file__).resolve().parent
    missing = [name for name in required if not (root / name).is_file()]
    results.append(HealthResult("application files", not missing,
                                "OK" if not missing else "missing " + ", ".join(missing)))
    return results

    # Read-only local checks: never contact banks, email or the physical printer.
