"""Repeatable, non-printing Pi checks; physical paper confirmation remains explicit."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PHASES = (
    "check",
    "baseline",
    "after-reboot",
    "disconnected",
    "reconnected",
    "after-recovery",
    "scheduled",
)


def boot_fingerprint():
    try:
        return hashlib.sha256(
            Path("/proc/sys/kernel/random/boot_id").read_bytes()
        ).hexdigest()
    except OSError:
        return None


def service_status():
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                "receipt-control.service",
                "--property=ActiveState",
                "--property=UnitFileState",
                "--property=MainPID",
                "--property=NRestarts",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return {}
        values = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        return {
            "active": values.get("ActiveState") == "active",
            "enabled": values.get("UnitFileState") == "enabled",
            "pid": int(values.get("MainPID", "0")),
            "restarts": int(values.get("NRestarts", "0")),
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def dependency_check(root=ROOT):
    missing = []
    try:
        lines = (Path(root) / "requirements.lock").read_text().splitlines()
    except OSError:
        return "pending", "Release dependency pins unavailable."
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            missing.append(name)
    return (
        ("failed", "Version mismatch: " + ", ".join(missing))
        if missing
        else ("passed", "Installed runtime dependencies match release pins.")
    )


def load_phases(root):
    from storage import PrivateStore

    return PrivateStore(
        Path(root) / "data" / "pi_acceptance.json",
        default=lambda: {"phases": {}},
        schema_version=1,
        migrations={0: lambda value: value},
        validate=lambda value: validate_state(value),
        max_bytes=100000,
    )


def validate_state(value):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("phases"), dict)
        or any(key not in PHASES for key in value["phases"])
    ):
        raise ValueError("Invalid Pi acceptance history.")
    for report in value["phases"].values():
        if not isinstance(report, dict) or not isinstance(report.get("evidence"), dict):
            raise ValueError("Invalid Pi acceptance evidence.")
        if (
            report.get("phase_complete") is not None
            and type(report["phase_complete"]) is not bool
        ):
            raise ValueError("Invalid Pi acceptance completion status.")


def check(
    *, root=ROOT, phase="check", offline=False, probe_printer=False, confirm_paper=False
):
    from web_control.printer_setup import installation_checks
    from receipt_settings import settings_state
    from web_control.schedule_history import summary

    root = Path(root)
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    for row in installation_checks(root):
        add(row["name"], "passed" if row["ok"] else "failed", row["detail"])
    status, detail = dependency_check(root)
    add("Release dependency versions", status, detail)
    settings, warning = settings_state()
    add(
        "Receipt settings",
        "failed" if warning else "passed",
        warning or "Settings loaded without recovery.",
    )
    service = {} if offline else service_status()
    add(
        "Service active and enabled",
        "passed"
        if service.get("active") and service.get("enabled")
        else "failed"
        if service
        else "pending",
        "Read-only systemd check; service changes are performed separately.",
    )
    boot = None if offline else boot_fingerprint()
    reachable = None
    if probe_printer and not offline:
        from receipt.printer import readiness

        reachable, message = readiness()
        add(
            "Printer connectivity",
            "passed"
            if reachable is True
            else "failed"
            if reachable is False
            else "pending",
            message,
        )
    else:
        add(
            "Printer connectivity",
            "pending",
            "Use --probe-printer for an explicit connection check without printing.",
        )
    daily = summary(settings, directory=root / "data")
    evidence = {
        "boot": boot,
        "service": service,
        "printer_reachable": reachable,
        "scheduled": daily["today"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    previous = load_phases(root).read()["phases"]
    baseline = previous.get("baseline", {}).get("evidence", {})
    if phase == "after-reboot":
        known = bool(boot and baseline.get("boot"))
        add(
            "Reboot observed",
            "passed"
            if known and boot != baseline["boot"]
            else "failed"
            if known
            else "pending",
            "Compare the boot fingerprint with a saved baseline; the tool never reboots the machine.",
        )
    if phase == "disconnected":
        add(
            "Printer disconnection observed",
            "passed"
            if reachable is False
            else "failed"
            if reachable is True
            else "pending",
            "Disconnect the printer separately, then use --probe-printer.",
        )
        # An expected disconnection is an acceptance result, not a failed connectivity check.
        for row in checks:
            if row["name"] == "Printer connectivity" and reachable is False:
                row["status"] = "passed"
    if phase == "reconnected":
        prior = previous.get("disconnected", {}).get("evidence", {})
        known = prior.get("printer_reachable") is False and reachable is not None
        add(
            "Printer reconnection observed",
            "passed" if known and reachable else "failed" if known else "pending",
            "Requires a saved disconnected check followed by an explicit connectivity check.",
        )
    if phase == "after-recovery":
        previous_pid = baseline.get("service", {}).get("pid")
        known = bool(previous_pid and service.get("pid"))
        add(
            "Service process restarted",
            "passed"
            if known and previous_pid != service["pid"] and service.get("active")
            else "failed"
            if known
            else "pending",
            "Compare process IDs with the baseline after separately exercising service recovery.",
        )
    if phase == "scheduled":
        recorded = daily["today"]
        fresh = bool(
            baseline.get("checked_at")
            and recorded.get("updated_at", "") > baseline["checked_at"]
        )
        add(
            "New scheduled outcome",
            "passed"
            if fresh and recorded["state"] == "sent"
            else "pending"
            if not fresh
            else "failed",
            recorded["label"],
        )
        add(
            "Paper collected",
            "passed"
            if confirm_paper and fresh and recorded["state"] == "sent"
            else "pending",
            "Operator confirmation only; software sending data does not prove paper delivery.",
        )
    else:
        add(
            "Paper collected",
            "pending",
            "Complete the scheduled phase and confirm the physical receipt with --confirm-paper.",
        )
    return {
        "phase": phase,
        "checked_at": evidence["checked_at"],
        "system": platform.system(),
        "architecture": platform.machine(),
        "checks": checks,
        "evidence": evidence,
        "result": "failed"
        if any(row["status"] == "failed" for row in checks)
        else "passed",
        "phase_complete": all(
            row["status"] == "passed"
            for row in checks
            if row["name"] != "Paper collected"
        ),
        "physical_complete": phase == "scheduled"
        and all(row["status"] == "passed" for row in checks)
        and all(
            previous.get(key, {}).get("phase_complete") is True
            for key in (
                "baseline",
                "after-reboot",
                "disconnected",
                "reconnected",
                "after-recovery",
            )
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, default="check")
    parser.add_argument(
        "--offline", action="store_true", help="Skip systemd and hardware calls"
    )
    parser.add_argument(
        "--probe-printer",
        action="store_true",
        help="Check connectivity without printing",
    )
    parser.add_argument(
        "--confirm-paper",
        action="store_true",
        help="Record your physical confirmation during the scheduled phase",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save this phase for comparison with later checks",
    )
    args = parser.parse_args()
    if args.confirm_paper and args.phase != "scheduled":
        parser.error("--confirm-paper belongs to the scheduled phase")
    try:
        report = check(
            phase=args.phase,
            offline=args.offline,
            probe_printer=args.probe_printer,
            confirm_paper=args.confirm_paper,
        )
        if args.save:
            load_phases(ROOT).update(
                lambda value: value["phases"].update({args.phase: report})
            )
        print(json.dumps(report, indent=2))
        return 1 if report["result"] == "failed" else 0
    except (OSError, ValueError) as error:
        print(json.dumps({"result": "failed", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
