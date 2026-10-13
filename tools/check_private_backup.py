#!/usr/bin/env python3
"""Backup diagnosis with an explicit, preserved weather-setting repair."""

import sys
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_control import private_backup


def main():
    root = Path(__file__).resolve().parents[1]
    if sys.argv[1:] == ["--repair-weather-detail"]:
        from receipt_settings import repair_weather_detail

        try:
            preserved = repair_weather_detail()
        except (OSError, ValueError):
            print(
                "Weather repair could not complete. No automatic settings reset was performed."
            )
            return 1
        print(
            "Weather detail is now full."
            if preserved
            else "Weather detail is already full."
        )
        if preserved:
            print("Original settings preserved as data/" + preserved.name + ".")
    elif sys.argv[1:]:
        print("Usage: python tools/check_private_backup.py [--repair-weather-detail]")
        return 1
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
