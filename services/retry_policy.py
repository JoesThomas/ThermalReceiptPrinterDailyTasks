"""Small shared retry policy; a single failure does not delay the next attempt."""

from datetime import datetime, timezone
import math


def delay(failures, *, base=60, maximum=3600):
    return 0 if failures < 2 else min(maximum, base * 2 ** min(failures - 2, 6))


def failures(value):
    return min(100, max(0, value)) if type(value) is int else 0


def retry_epoch(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return 0


def pending(value, now=None):
    import time

    try:
        return datetime.fromisoformat(value).timestamp() > (
            time.time() if now is None else now
        )
    except (TypeError, ValueError, OverflowError):
        return False


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None
