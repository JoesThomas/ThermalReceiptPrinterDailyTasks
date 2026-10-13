#!/usr/bin/env python3
"""Read-only backup diagnosis, without printing private values or writing files."""

import sys
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_control import private_backup


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        private_backup.export(root)
    except (OSError, ValueError) as error:
        print("Backup check: " + private_backup.failure_message(error))
        return 1
    print("Backup check: supported local files are valid.")
    try:
        print(f"Free disk space: {shutil.disk_usage(root).free // (1024 * 1024)} MiB")
    except OSError:
        print("Free disk space could not be checked.")
    print("No files were changed. Use Save snapshot now to test writing a backup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
