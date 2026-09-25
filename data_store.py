from __future__ import annotations

import fcntl
import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MAX_BACKUPS = 5


class JsonDataError(RuntimeError):
    pass


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _backup_dir(path: Path) -> Path:
    return path.parent / "backups" / path.name


def _read_unlocked(path: Path, default):
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as error:
        raise JsonDataError(
            f"Invalid JSON in {path}: {error}"
        ) from error
    except OSError as error:
        raise JsonDataError(
            f"Could not read {path}: {error}"
        ) from error


def read_json(path: Path, default):
    path = Path(path)
    lock_path = _lock_path(path)
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with lock_path.open("a+") as lock_file:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_SH,
        )
        try:
            return _read_unlocked(
                path,
                default,
            )
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )


def _make_backup(path: Path) -> None:
    if not path.exists():
        return

    backup_dir = _backup_dir(path)
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S%fZ")

    backup = (
        backup_dir
        / f"{stamp}.json"
    )

    shutil.copy2(
        path,
        backup,
    )

    backups = sorted(
        backup_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for old in backups[MAX_BACKUPS:]:
        old.unlink(
            missing_ok=True
        )


def _write_unlocked(
    path: Path,
    value,
    *,
    backup: bool = True,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if backup:
        _make_backup(
            path
        )

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    os.chmod(
        temp,
        0o600,
    )

    temp.replace(
        path
    )

    os.chmod(
        path,
        0o600,
    )


def write_json(
    path: Path,
    value,
    *,
    backup: bool = True,
) -> None:
    path = Path(path)
    lock_path = _lock_path(path)
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with lock_path.open("a+") as lock_file:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )
        try:
            # Refuse to overwrite a corrupted existing file.
            if path.exists():
                _read_unlocked(
                    path,
                    None,
                )

            _write_unlocked(
                path,
                value,
                backup=backup,
            )
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )


@contextmanager
def edit_json(
    path: Path,
    default,
    *,
    backup: bool = True,
):
    """
    Lock one JSON file across the complete
    read-modify-write transaction.
    """
    path = Path(path)
    lock_path = _lock_path(path)
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with lock_path.open("a+") as lock_file:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            value = _read_unlocked(
                path,
                default,
            )

            yield value

            _write_unlocked(
                path,
                value,
                backup=backup,
            )

        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )
