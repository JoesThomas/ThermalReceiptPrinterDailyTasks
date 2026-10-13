"""Prepare validated candidates and activate/rollback only on an explicit CLI command."""

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import venv
from storage import write_json, write_bytes
from web_control import private_backup

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "receipt-control.service"


def run(command, root, *, input=None, timeout=600):
    return subprocess.run(
        command, cwd=root, input=input, capture_output=True, timeout=timeout, check=True
    ).stdout


def revision(root, ref="HEAD"):
    if not ref or ref.startswith("-") or len(ref) > 200:
        raise ValueError("Choose a valid local Git reference.")
    value = (
        run(["git", "rev-parse", "--verify", ref + "^{commit}"], root).decode().strip()
    )
    if not re.fullmatch(r"[a-f0-9]{40,64}", value):
        raise ValueError("Invalid commit identifier.")
    return value


def clean(root):
    if run(["git", "status", "--porcelain", "--untracked-files=no"], root).strip():
        raise ValueError(
            "Tracked files have local changes. Commit or preserve them before updating."
        )


def directory(root, identifier):
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid update identifier.")
    return Path(root) / "data" / "updates" / identifier


def read_state(root, identifier):
    from storage import PrivateStore

    folder = directory(root, identifier)
    value = PrivateStore(folder / "state.json", default=dict, max_bytes=100000).read()
    if (
        not isinstance(value, dict)
        or value.get("format") != 1
        or value.get("id") != identifier
        or any(
            not isinstance(value.get(key), str)
            or not re.fullmatch(r"[a-f0-9]{40,64}", value[key])
            for key in ("target", "previous")
        )
        or value.get("phase")
        not in {
            "preparing",
            "prepare_failed",
            "prepared",
            "applying",
            "applied",
            "apply_failed",
            "rolled_back",
            "recovery_required",
        }
    ):
        raise ValueError("Invalid update checkpoint.")
    return value


def save(root, state):
    write_json(directory(root, state["id"]) / "state.json", state)


def snapshot(root):
    files = {}
    total = 0
    for name in sorted(private_backup.FILES):
        path = Path(root) / "data" / name
        if path.is_symlink():
            raise ValueError(
                "Linked settings files need a manual update/backup workflow."
            )
        if path.exists():
            with path.open("rb") as stream:
                raw = stream.read(private_backup.MAX_BYTES + 1)
            total += len(raw)
            if total > private_backup.MAX_BYTES:
                raise ValueError(
                    "Settings exceed the supported backup size; use a manual update workflow."
                )
            files[name] = base64.b64encode(raw).decode()
        else:
            files[name] = None
    return {"format": 1, "files": files}


def config_payload(snapshot):
    files = {
        name: private_backup.file_content(name, base64.b64decode(raw, validate=True))
        for name, raw in snapshot["files"].items()
        if raw is not None
    }
    return json.dumps({"version": 1, "files": files}).encode() if files else None


def restore(root, checkpoint):
    if checkpoint.get("format") != 1 or not set(checkpoint.get("files", {})).issubset(
        private_backup.FILES
    ):
        raise ValueError("Unsupported settings checkpoint.")
    for name, raw in checkpoint["files"].items():
        path = Path(root) / "data" / name
        if path.is_symlink():
            raise ValueError("Cannot replace linked settings.")
        if raw is None:
            path.unlink(missing_ok=True)
        else:
            write_bytes(path, base64.b64decode(raw, validate=True))


def environment(root, identifier):
    # A permanent service-user-owned path keeps venv shebangs valid after activation.
    return directory(root, identifier) / "environment"


def validate_candidate(root, candidate, python, checkpoint):
    run([str(python), "-m", "compileall", "-q", str(candidate)], candidate)
    run(
        [str(python), str(candidate / "tools" / "pi_acceptance.py"), "--offline"],
        candidate,
    )
    payload = config_payload(checkpoint)
    if payload:
        # Validate against the candidate's schemas, without copying private data into it.
        run(
            [
                str(python),
                "-c",
                "import sys; from web_control.private_backup import validate; validate(sys.stdin.buffer.read())",
            ],
            candidate,
            input=payload,
        )


def prepare(root, ref, *, fetch=False, validate=validate_candidate, install=True):
    root = Path(root)
    clean(root)
    if fetch:
        run(["git", "fetch", "origin", "main"], root)
    target = revision(root, ref)
    previous = revision(root)
    identifier = uuid.uuid4().hex
    folder = directory(root, identifier)
    folder.mkdir(parents=True, mode=0o700)
    candidate = folder / "candidate"
    env = environment(root, identifier)
    state = {
        "format": 1,
        "id": identifier,
        "target": target,
        "previous": previous,
        "phase": "preparing",
        "original_python": sys.executable,
        "stage": "creating candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save(root, state)
    before = snapshot(root)
    write_json(folder / "prepare-settings.json", before)
    try:
        run(["git", "worktree", "add", "--detach", str(candidate), target], root)
        if install:
            state["stage"] = "installing dependencies"
            save(root, state)
            env.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            venv.EnvBuilder(with_pip=True).create(env)
            run(
                [
                    str(env / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(candidate / "requirements.lock"),
                ],
                candidate,
            )
        state["stage"] = "validating candidate"
        save(root, state)
        validate(root, candidate, env / "bin" / "python", before)
        state["phase"] = "prepared"
        save(root, state)
        return state
    except Exception as error:
        state["phase"] = "prepare_failed"
        state["error_type"] = type(error).__name__
        save(root, state)
        raise ValueError(
            f"Preparation failed during {state['stage']}. Checkpoint {identifier} is preserved; live code is unchanged."
        ) from None


def previous_environment(root, identifier):
    current = Path(root) / ".venv"
    if current.is_symlink():
        return {"kind": "link", "target": os.readlink(current)}
    if current.exists():
        return {
            "kind": "directory",
            "target": str(environment(root, identifier).parent / "previous-env"),
        }
    return None


def switch_environment(root, target, identifier, previous):
    current = Path(root) / ".venv"
    if previous and previous["kind"] == "directory":
        current.rename(previous["target"])
    temporary = Path(root) / (".venv-next-" + identifier)
    try:
        temporary.symlink_to(target, target_is_directory=True)
        temporary.replace(current)
    finally:
        temporary.unlink(missing_ok=True)


def restore_environment(root, previous):
    current = Path(root) / ".venv"
    if current.exists() and not current.is_symlink():
        if (
            previous
            and previous["kind"] == "directory"
            and not Path(previous["target"]).exists()
        ):
            return
        raise ValueError("The active environment was replaced; recover it manually.")
    current.unlink(missing_ok=True)
    if previous:
        if previous["kind"] == "directory":
            Path(previous["target"]).rename(current)
        else:
            current.symlink_to(previous["target"], target_is_directory=True)


def service(root, action):
    run(["systemctl", action, SERVICE], root, timeout=45)


def guard(root, stopped):
    if not stopped:
        raise ValueError(
            "Stop the web app first and pass --stopped, or explicitly choose --service on the Pi."
        )
    from receipt.printer_status import busy

    if busy(root):
        raise ValueError(
            "A receipt worker is still active. Cancel it or wait before updating."
        )


def apply(
    root,
    identifier,
    *,
    stopped=False,
    manage_service=False,
    validate=validate_candidate,
):
    root = Path(root)
    state = read_state(root, identifier)
    if state["phase"] != "prepared":
        raise ValueError("Prepare and validate this candidate before applying it.")
    clean(root)
    if revision(root) != state["previous"]:
        raise ValueError("The checkout changed since preparation. Prepare again.")
    candidate = directory(root, identifier) / "candidate"
    clean(candidate)
    if revision(candidate) != state["target"]:
        raise ValueError("Prepared candidate changed; prepare it again.")
    env = environment(root, identifier)
    if manage_service:
        service(root, "stop")
    changed = False
    try:
        guard(root, stopped or manage_service)
        checkpoint = snapshot(root)
        validate(root, candidate, env / "bin" / "python", checkpoint)
        write_json(directory(root, identifier) / "before-apply.json", checkpoint)
        state.update(
            phase="applying",
            previous_environment=previous_environment(root, identifier),
        )
        save(root, state)
        # Keep ignored/untracked private files; never force a dirty checkout.
        run(
            ["git", "checkout", "--no-overwrite-ignore", "--detach", state["target"]],
            root,
        )
        changed = True
        switch_environment(root, env, identifier, state["previous_environment"])
        save(root, state)
        if manage_service:
            service(root, "start")
            run(["systemctl", "is-active", "--quiet", SERVICE], root, timeout=10)
        state["phase"] = "applied"
        save(root, state)
        return state
    except Exception:
        try:
            if manage_service:
                service(root, "stop")
            if changed:
                write_json(
                    directory(root, identifier) / "failed-update-settings.json",
                    snapshot(root),
                )
                run(
                    [
                        "git",
                        "checkout",
                        "--no-overwrite-ignore",
                        "--detach",
                        state["previous"],
                    ],
                    root,
                )
                restore_environment(root, state.get("previous_environment"))
                restore(root, checkpoint)
            state["phase"] = "rolled_back" if changed else "apply_failed"
            save(root, state)
            if manage_service:
                service(root, "start")
        except Exception:
            state["phase"] = "recovery_required"
            save(root, state)
            raise ValueError(
                "Update recovery is incomplete. Keep the service stopped and recover from the private before-apply checkpoint."
            ) from None
        raise


def rollback(
    root,
    identifier,
    *,
    stopped=False,
    manage_service=False,
    restore_settings=False,
    validate=validate_candidate,
):
    root = Path(root)
    state = read_state(root, identifier)
    if state["phase"] != "applied":
        raise ValueError(
            "This update has not been applied or has already been rolled back."
        )
    clean(root)
    if revision(root) != state["target"]:
        raise ValueError("The active revision changed. Use its own update checkpoint.")
    if manage_service:
        service(root, "stop")
    changed = False
    current = None
    try:
        guard(root, stopped or manage_service)
        current = snapshot(root)
        from storage import PrivateStore

        checkpoint = (
            PrivateStore(
                directory(root, identifier) / "before-apply.json", default=dict
            ).read()
            if restore_settings
            else current
        )
        old = directory(root, identifier) / "rollback-candidate"
        if not old.exists():
            run(
                ["git", "worktree", "add", "--detach", str(old), state["previous"]],
                root,
            )
        previous = state.get("previous_environment")
        if previous:
            old_environment = Path(previous["target"])
            if not old_environment.is_absolute():
                old_environment = root / old_environment
            python = old_environment / "bin" / "python"
        else:
            python = Path(state.get("original_python", sys.executable))
        validate(root, old, python, checkpoint)
        write_json(directory(root, identifier) / "before-rollback.json", current)
        run(
            ["git", "checkout", "--no-overwrite-ignore", "--detach", state["previous"]],
            root,
        )
        changed = True
        restore_environment(root, previous)
        if restore_settings:
            restore(root, checkpoint)
        state["phase"] = "rolled_back"
        save(root, state)
        if manage_service:
            service(root, "start")
        return state
    except Exception:
        if changed:
            try:
                if manage_service:
                    service(root, "stop")
                run(
                    [
                        "git",
                        "checkout",
                        "--no-overwrite-ignore",
                        "--detach",
                        state["target"],
                    ],
                    root,
                )
                active = previous_environment(root, identifier)
                switch_environment(
                    root, environment(root, identifier), identifier, active
                )
                restore(root, current)
                state["phase"] = "applied"
                save(root, state)
            except Exception:
                state["phase"] = "recovery_required"
                save(root, state)
                raise ValueError(
                    "Rollback recovery is incomplete. Keep the service stopped and recover from the private before-rollback checkpoint."
                ) from None
        if manage_service:
            service(root, "start")
        raise
