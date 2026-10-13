"""Explicit, checkpointed update commands. Preparing never switches live code."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment import update_helper as updates
from storage import file_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("ref", nargs="?", default="origin/main")
    prepare.add_argument("--fetch", action="store_true")
    for command in ("apply", "rollback"):
        action = sub.add_parser(command)
        action.add_argument("identifier")
        action.add_argument("--stopped", action="store_true")
        action.add_argument("--service", action="store_true")
        if command == "rollback":
            action.add_argument(
                "--restore-settings",
                action="store_true",
                help="Restore pre-update settings; preserve current settings in the rollback checkpoint first",
            )
    args = parser.parse_args()
    try:
        with file_lock(ROOT / "data" / "update_guard", blocking=False):
            if args.command == "prepare":
                print(
                    "Preparing an isolated candidate and pinned environment; live code is unchanged.",
                    flush=True,
                )
                state = updates.prepare(ROOT, args.ref, fetch=args.fetch)
            else:
                kwargs = {"stopped": args.stopped, "manage_service": args.service}
                if args.command == "rollback":
                    kwargs["restore_settings"] = args.restore_settings
                state = getattr(updates, args.command)(ROOT, args.identifier, **kwargs)
        print(
            json.dumps(
                {key: state[key] for key in ("id", "phase", "previous", "target")},
                indent=2,
            )
        )
        print(
            "Review the checkpoint before applying. Reactivate your virtual environment after an apply or rollback."
        )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "checkpoint": getattr(args, "identifier", None),
                    "error_type": type(error).__name__,
                    "detail": str(error)
                    if isinstance(error, ValueError)
                    else "Operation failed; inspect the private checkpoint and service status before retrying.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
