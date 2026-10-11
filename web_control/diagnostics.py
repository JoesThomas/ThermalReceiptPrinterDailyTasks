"""Allowlisted diagnostic export: no raw logs, settings, URLs or transaction data."""
import json
import platform
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from services import api_health, source_cache
from receipt.capture import CAPTURE_FILE, LIVE_PREVIEW_FILE, load_capture

ROOT = Path(__file__).resolve().parents[1]


def export():
    packages = {}
    for name in ('Flask', 'waitress', 'python-escpos', 'requests', 'icalendar'):
        try: packages[name] = version(name)
        except PackageNotFoundError: packages[name] = 'not installed'
    health = {}
    for name, row in api_health.load().get('services', {}).items():
        if name not in (*api_health.PUBLIC, *api_health.OBSERVED, 'Google Calendar') or not isinstance(row, dict): continue
        health[name] = {key: row.get(key) for key in ('checked_at','status','code','duration_ms','mode','reason','last_success')}
    jobs = {}
    for name in ('web_print_status.json', 'live_preview_status.json'):
        try: row = json.loads((ROOT/'data'/name).read_text())
        except (OSError, ValueError): continue
        if not isinstance(row, dict): continue
        # Progress stages may contain personal source text; omit them and raw errors.
        jobs[name.removesuffix('.json')] = {key: row.get(key) for key in ('state','completed','total','started_at','updated_at')}
    checks = {}
    for path in (CAPTURE_FILE, LIVE_PREVIEW_FILE):
        for name, row in (load_capture(path) or {}).get('freshness', {}).items():
            if name in (*api_health.PUBLIC, *api_health.OBSERVED, 'Calendar', 'Deliveries'):
                checks[name] = {key: row.get(key) for key in ('status','checked_at','source_checked_at','duration_ms')}
    return {'format':1,'python':platform.python_version(),'system':platform.system(),
            'packages':packages,'jobs':jobs,'services':health,'source_checks':checks,
            'source_timings':source_cache.timings()}
