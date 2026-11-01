"""Short, server-only unlocks and one-use operation tickets; never signed-cookie keys."""

import secrets
import time
from threading import RLock, Timer

TTL = 300
COOKIE = "__Secure-receipt-smart-home"
LOCK = RLock()
ROWS = {}


def cleanup():
    now = time.monotonic()
    for key, row in list(ROWS.items()):
        if row["expires"] <= now:
            revoke(key)


def create(binding, key, **extra):
    with LOCK:
        cleanup()
        if len(ROWS) >= 8:
            raise ValueError(
                "Too many smart-home unlock sessions; lock another session first."
            )
        token = secrets.token_urlsafe(32)
        ROWS[token] = dict(
            binding=binding,
            key=key,
            expires=time.monotonic() + TTL,
            tickets={},
            views={},
            busy=False,
            **extra,
        )
        timer = Timer(TTL + 1, expire)
        timer.daemon = True
        ROWS[token]["timer"] = timer
        timer.start()
        return token


def get(token, binding):
    with LOCK:
        cleanup()
        row = ROWS.get(token)
        return row if row and secrets.compare_digest(row["binding"], binding) else None


def revoke(token):
    with LOCK:
        row = ROWS.pop(token, None)
        if row:
            timer = row.pop("timer", None)
            if timer:
                timer.cancel()
            row["key"] = b""
            row["views"].clear()
            row["tickets"].clear()
            row.pop("seed", None)
            row.pop("codes", None)


def revoke_binding(binding):
    with LOCK:
        for token, row in list(ROWS.items()):
            if secrets.compare_digest(row["binding"], binding):
                revoke(token)


def ticket(row, action, identifier=""):
    with LOCK:
        now = time.monotonic()
        row["tickets"] = {k: v for k, v in row["tickets"].items() if v[2] > now}
        if len(row["tickets"]) >= 512:
            row["tickets"].pop(next(iter(row["tickets"])))
        token = secrets.token_urlsafe(24)
        row["tickets"][token] = (action, identifier, min(row["expires"], now + 120))
        return token


def consume(row, token, action, identifier=""):
    with LOCK:
        record = row["tickets"].pop(token, None)
        return bool(
            record
            and record[:2] == (action, identifier)
            and time.monotonic() < record[2]
            and time.monotonic() < row["expires"]
        )


def expire():
    with LOCK:
        cleanup()


def revoke_all():
    with LOCK:
        for token in list(ROWS):
            revoke(token)
