"""Small allowlisted local-device interface in a disposable process."""

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from threading import BoundedSemaphore
from smart_home.vault import host

TYPES = {
    "camera": {"camera"},
    "plug": {"plug", "wallswitch", "stripsocket"},
    "light": {"bulb", "dimmer", "lightstrip"},
    "thermostat": {"thermostat"},
    "sensor": {"sensor"},
}
NUMBER = {
    "brightness": (0, 100, 1),
    "color_temperature": (1500, 9000, 1),
    "target_temperature": (5, 30, 0.5),
}
READ = {
    "state",
    "brightness",
    "color_temperature",
    "current_temperature",
    "temperature",
    "target_temperature",
    "humidity",
    "current_humidity",
    "current_power",
    "voltage",
    "current",
    "temperature_unit",
}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def describe(dev, kind):
    actual = dev.device_type.value
    if actual not in TYPES.get(kind, set()):
        raise ValueError("Device category does not match its reported capabilities.")
    features = dev.features
    readings = []
    controls = []
    for name in sorted(READ):
        feature = features.get(name)
        if not feature:
            continue
        value = feature.value
        if not (
            type(value) is bool
            or finite(value)
            or isinstance(value, str)
            and len(value) <= 40
        ):
            continue
        unit = str(getattr(feature, "unit", "") or "")[:16]
        readings.append(
            dict(id=name, label=str(feature.name)[:80], value=value, unit=unit)
        )
    if kind == "camera":
        if f := features.get("state"):
            if f.attribute_setter is not None and type(f.value) is bool:
                controls.extend(
                    [
                        dict(action="privacy_on", label="Enable privacy"),
                        dict(action="privacy_off", label="Disable privacy"),
                    ]
                )
        for action in ("pan_left", "pan_right", "tilt_up", "tilt_down"):
            if action in features and features[action].attribute_setter is not None:
                controls.append(
                    dict(action=action, label=action.replace("_", " ").capitalize())
                )
    elif kind in {"plug", "light"}:
        if f := features.get("state"):
            if f.attribute_setter is not None and type(f.value) is bool:
                controls.extend(
                    [
                        dict(action="on", label="Turn on"),
                        dict(action="off", label="Turn off"),
                    ]
                )
    for name, (low, high, step) in NUMBER.items():
        if (
            name == "target_temperature"
            and kind != "thermostat"
            or name != "target_temperature"
            and kind != "light"
        ):
            continue
        f = features.get(name)
        if not f or f.attribute_setter is None:
            continue
        unit = str(getattr(f, "unit", "") or "").casefold()
        if name == "target_temperature":
            if not unit and (unit_feature := features.get("temperature_unit")):
                unit = str(unit_feature.value).casefold()
            if unit not in {"c", "°c", "celsius"}:
                continue
        minimum, maximum = f.minimum_value, f.maximum_value
        if not finite(minimum) or not finite(maximum):
            continue
        low, high = max(low, minimum), min(high, maximum)
        if low > high:
            continue
        controls.append(
            dict(
                action=name,
                label=str(f.name)[:80],
                minimum=low,
                maximum=high,
                step=step,
                current=f.value if finite(f.value) and low <= f.value <= high else low,
            )
        )
    mac = str(dev.mac or "")
    model = str(dev.model or "")[:80]
    identifier = str(dev.device_id or "")
    if not identifier or not re.fullmatch(r"[a-fA-F0-9:-]{12,17}", mac):
        raise ValueError("Device identity is unavailable.")
    fingerprint = hashlib.sha256(
        json.dumps([identifier, mac.lower(), model]).encode()
    ).hexdigest()
    return dict(
        model=model,
        mac=mac,
        fingerprint=fingerprint,
        readings=readings,
        controls=controls,
    )


async def apply(dev, kind, action, value):
    info = describe(dev, kind)
    control = next((c for c in info["controls"] if c["action"] == action), None)
    if not control:
        raise ValueError("This action is not supported by the selected device.")
    if action in {"privacy_on", "privacy_off", "on", "off"}:
        await dev.features["state"].set_value(action in {"privacy_off", "on"})
    elif action in {"pan_left", "pan_right", "tilt_up", "tilt_down"}:
        step = "pan_step" if action.startswith("pan_") else "tilt_step"
        if step not in dev.features:
            raise ValueError("Bounded camera movement is unavailable.")
        await dev.features[step].set_value(5)
        await dev.features[action].set_value(None)
    elif action in NUMBER:
        try:
            number = float(value)
        except (ValueError, TypeError):
            raise ValueError("Enter a numeric device setting.") from None
        if (
            not math.isfinite(number)
            or not control["minimum"] <= number <= control["maximum"]
            or abs(number / control["step"] - round(number / control["step"])) > 1e-7
        ):
            raise ValueError("Device setting is outside the permitted range or step.")
        await dev.features[action].set_value(
            number if control["step"] < 1 else int(number)
        )
    return info


def _run(device, action="status", value=None):
    if device.get("kind") != "yale_alarm":
        host(device["host"])
    payload = {"device": device, "action": action, "value": value}
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("worker.py"))],
            input=json.dumps(payload).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=28 if device.get("kind") == "yale_alarm" else 18,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ValueError(
            "Device timed out. A command may have arrived; refresh status before retrying."
        ) from None
    if process.returncode or len(process.stdout) > 50000:
        raise ValueError(
            "Device connection failed. Check its address, credentials and third-party compatibility setting."
        )
    try:
        result = json.loads(process.stdout)
    except ValueError:
        raise ValueError("Invalid device response.") from None
    if not isinstance(result, dict) or not result.get("ok"):
        reason = result.get("error") if isinstance(result, dict) else None
        messages = {
            "dependency": "Install the optional smart-home requirements first.",
            "identity": "Device identity changed. No command was sent; remove and pair the device again after checking it.",
            "category": "The reported device category or capability does not match the saved device.",
            "failed": "Device check failed. A command may have arrived; refresh status before retrying.",
            "yale": "Device check failed for Yale. Check the Yale app, account verification and selected alarm. A command may have arrived; check its status before retrying.",
        }
        raise ValueError(messages.get(reason, messages["failed"]))
    return result["data"]


WORKERS = BoundedSemaphore(2)


def run(device, action="status", value=None):
    if not WORKERS.acquire(blocking=False):
        raise ValueError(
            "Device requests are busy. Wait briefly and refresh status before retrying."
        )
    try:
        return _run(device, action, value)
    finally:
        WORKERS.release()
