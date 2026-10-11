"""Collect independent sources concurrently; callers render results in their own order."""

from concurrent.futures import ThreadPoolExecutor


def collect_independent(tasks, *, max_workers=4):
    if not tasks:
        return {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        # Keep each exception on its future, so one failure cannot hide other results.
        return {name: pool.submit(collect) for name, collect in tasks.items()}
