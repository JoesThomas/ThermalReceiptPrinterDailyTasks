"""Bound web jobs and stop their isolated child process groups on cancellation."""
import os
import signal
import subprocess
from datetime import datetime, timezone

MAX_SECONDS = 600


class JobCancelled(Exception):
    pass


def run_bounded(command, *, cwd, env, timeout=MAX_SECONDS):
    child = None
    def cancel(signum, frame):
        raise JobCancelled()
    previous = signal.signal(signal.SIGTERM, cancel)
    try:
        child = subprocess.Popen(command, cwd=cwd, env={**env, 'PYTHONUNBUFFERED': '1'},
                                 start_new_session=True)
        return child.wait(timeout=timeout)
    finally:
        # Ignore repeated cancellation until cleanup finishes.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                # A helper may survive its parent; clear the remaining child group too.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            signal.signal(signal.SIGTERM, previous)


def log_event(job_id, text):
    print(f'{datetime.now(timezone.utc).isoformat()} job={job_id} {text}', flush=True)


def release_owned_lock(lock, pid=None):
    """A finishing worker must not remove a lock belonging to a newer job."""
    pid = os.getpid() if pid is None else pid
    try:
        if lock.read_text().strip() == str(pid):
            lock.unlink(missing_ok=True)
    except OSError:
        pass
