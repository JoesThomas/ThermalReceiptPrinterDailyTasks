"""Reap completed workers and release only their own job lock."""
from threading import Thread


def wait_for_job(process, lock):
    process.wait()
    try:
        if lock.read_text(encoding="utf-8").strip() == str(process.pid):
            lock.unlink(missing_ok=True)
    except OSError:
        pass


def watch_job(process, lock):
    Thread(target=wait_for_job, args=(process, lock), daemon=True,
           name="receipt-job-cleanup").start()
