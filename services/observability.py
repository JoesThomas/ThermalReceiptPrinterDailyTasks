"""Small, allowlisted integration events; never log payloads or exception text."""

import json
import logging
from contextlib import contextmanager
from time import perf_counter

LOGGER = logging.getLogger("receipt.integrations")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def event(
    operation, *, provider=None, status="ok", seconds=None, error=None, count=None
):
    row = {"operation": operation, "status": status}
    if provider is not None:
        row["provider"] = provider
    if seconds is not None:
        row["seconds"] = round(seconds, 3)
    if count is not None:
        row["count"] = count
    if error is not None:
        row["error_type"] = type(error).__name__
        response = getattr(error, "response", None)
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            row["http_status"] = code
    LOGGER.log(logging.WARNING if status == "failed" else logging.INFO, json.dumps(row))


@contextmanager
def timed(operation, *, provider=None):
    start = perf_counter()
    try:
        yield
    except Exception as error:
        event(
            operation,
            provider=provider,
            status="failed",
            seconds=perf_counter() - start,
            error=error,
        )
        raise
    else:
        event(operation, provider=provider, seconds=perf_counter() - start)
