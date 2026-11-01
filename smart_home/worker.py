"""No command-line credentials, debug logging, arbitrary commands or raw exceptions."""

import asyncio
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smart_home import devices
from smart_home.vault import host


async def work(payload):
    try:
        from kasa import Credentials, Discover
    except ImportError:
        return dict(ok=False, error="dependency")
    row = payload["device"]
    address = host(row["host"])
    root = None
    try:
        root = await Discover.discover_single(
            address,
            credentials=Credentials(row["username"], row["password"]),
            discovery_timeout=3,
            timeout=4,
        )
        if not root or root.host != address:
            raise ValueError("Unexpected device")
        await root.update()
        dev = root
        if row.get("child_id"):
            dev = next(
                (c for c in root.children if c.device_id == row["child_id"]), None
            )
            if dev is None:
                return dict(ok=False, error="category")
        data = devices.describe(dev, row["kind"])
        if row.get("pin") and data["fingerprint"] != row["pin"]:
            return dict(ok=False, error="identity")
        action = payload.get("action", "status")
        if action != "status":
            if not row.get("pin"):
                return dict(ok=False, error="identity")
            await devices.apply(dev, row["kind"], action, payload.get("value"))
            await root.update()
            data = devices.describe(dev, row["kind"])
        return dict(ok=True, data=data)
    except Exception:
        return dict(ok=False, error="failed")
    finally:
        if root:
            try:
                await root.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("Invalid request")
        payload = json.loads(raw)
        if payload.get("device", {}).get("kind") == "yale_alarm":
            from smart_home.yale import work as yale_work

            result = yale_work(payload)
        else:
            result = asyncio.run(asyncio.wait_for(work(payload), timeout=15))
    except Exception:
        result = dict(ok=False, error="failed")
    print(json.dumps(result, allow_nan=False))
