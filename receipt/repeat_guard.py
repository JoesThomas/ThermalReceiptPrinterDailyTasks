"""Warn about recent identical print requests; never claim paper was produced."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from storage import write_json


def key(args): return hashlib.sha256(json.dumps(args, separators=(',', ':')).encode()).hexdigest()


def recent(root, args, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        value = json.loads((root / 'data' / 'recent_print_request.json').read_text())
        elapsed = (now - datetime.fromisoformat(value['at'])).total_seconds()
        return value['key'] == key(args) and 0 <= elapsed < 180
    except (OSError, ValueError, TypeError, KeyError): return False


def record(root, args):
    write_json(root / 'data' / 'recent_print_request.json', {'key': key(args), 'at': datetime.now(timezone.utc).isoformat()})
