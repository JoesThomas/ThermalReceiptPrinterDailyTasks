"""Opt-in archive retention; pinned and invalid receipts are never removed."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from storage import PrivateStore, file_lock, write_json
from receipt import archive

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}")
DAYS = (30, 90, 180, 365)


def validate(state):
    if not isinstance(state, dict) or state.get("keep_days") not in (None, *DAYS):
        raise ValueError("Choose keep all, 30, 90, 180 or 365 days.")
    from storage import validate_schema_version
    validate_schema_version(state, 1)
    pins = state.get("pins", [])
    if (
        not isinstance(pins, list)
        or len(pins) > 5000
        or any(not isinstance(i, str) or not IDENTIFIER.fullmatch(i) for i in pins)
        or len(set(pins)) != len(pins)
    ):
        raise ValueError("Invalid pinned receipts.")
    if state.get("last_pruned") is not None:
        datetime.fromisoformat(state["last_pruned"])


def store(root=ROOT):
    return PrivateStore(
        Path(root) / "data" / "receipt_archive_settings.json",
        default=lambda: {"keep_days": None, "pins": [], "last_pruned": None},
        validate=validate, schema_version=1, migrations={0: lambda value: value},
    )


def options(root=ROOT):
    return store(root).read()


def save(days, root=ROOT):
    if days not in (None, *DAYS):
        raise ValueError("Invalid retention period.")

    def change(state):
        state.update(keep_days=days, last_pruned=None)

    return store(root).update(change)


def pin(identifier, enabled, root=ROOT):
    archive.load(identifier)

    def change(state):
        pins = set(state["pins"])
        if enabled:
            pins.add(identifier)
        else:
            pins.discard(identifier)
        state["pins"] = sorted(pins)

    return store(root).update(change)


def usage(root=ROOT):
    state = options(root)
    files = []
    for path in archive.DIRECTORY.glob("*.json"):
        if path.is_symlink() or not IDENTIFIER.fullmatch(path.stem):
            continue
        try:
            files.append((path.stem, path.stat().st_size))
        except OSError:
            pass
    return {
        "count": len(files),
        "bytes": sum(size for _, size in files),
        "mib": sum(size for _, size in files) / 1048576,
        "pinned": sum(identifier in state["pins"] for identifier, _ in files),
    }


def prune(root=ROOT, *, now=None, force=False):
    now = now or datetime.now(timezone.utc)
    state_store = store(root)
    with file_lock(state_store.path):
        state = state_store.read()
        if state["keep_days"] is None:
            return 0
        if (
            not force
            and state.get("last_pruned")
            and datetime.fromisoformat(state["last_pruned"]).date() == now.date()
        ):
            return 0
        cutoff = now - timedelta(days=state["keep_days"])
        deleted = 0
        for path in archive.DIRECTORY.glob("*.json"):
            if (
                path.is_symlink()
                or path.stem in state["pins"]
                or not IDENTIFIER.fullmatch(path.stem)
            ):
                continue
            try:
                item = archive.load(path.stem)
                captured = datetime.fromisoformat(item["captured_at"])
                if captured.tzinfo is not None and captured < cutoff:
                    path.unlink()
                    deleted += 1
            except (ValueError, OSError, TypeError):
                continue
        state["schema_version"] = 1
        state["last_pruned"] = now.isoformat()
        write_json(state_store.path, state)
        archive._entry_summary.cache_clear()
        return deleted
