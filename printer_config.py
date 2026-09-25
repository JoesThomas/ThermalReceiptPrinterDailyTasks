from __future__ import annotations

import json
import socket
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = PROJECT_ROOT / "data" / "printer_settings.json"

DEFAULT_SETTINGS = {
    "connection": "usb",
    "usb": {
        "vendor_id": "0x0416",
        "product_id": "0x5011",
    },
    "network": {
        "host": "",
        "port": 9100,
    },
}


def _merge(defaults, supplied):
    result = deepcopy(defaults)

    if not isinstance(supplied, dict):
        return result

    for key, value in supplied.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _merge(
                result[key],
                value,
            )
        elif key in result:
            result[key] = value

    return result


def load_printer_settings():
    if not SETTINGS_FILE.exists():
        return deepcopy(DEFAULT_SETTINGS)

    try:
        raw = json.loads(
            SETTINGS_FILE.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return deepcopy(DEFAULT_SETTINGS)

    return _merge(
        DEFAULT_SETTINGS,
        raw,
    )


def save_printer_settings(settings):
    SETTINGS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = SETTINGS_FILE.with_suffix(
        ".tmp"
    )

    temp.write_text(
        json.dumps(
            settings,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temp.replace(
        SETTINGS_FILE
    )


def _parse_int(value, default):
    if isinstance(value, int):
        return value

    text = str(value or "").strip()

    if not text:
        return default

    try:
        return int(
            text,
            0,
        )
    except ValueError:
        return default


def printer_connection_label(settings=None):
    settings = (
        settings
        or load_printer_settings()
    )

    connection = str(
        settings.get(
            "connection",
            "usb",
        )
    ).lower()

    if connection == "network":
        network = settings.get(
            "network",
            {},
        )

        host = str(
            network.get(
                "host",
                "",
            )
        ).strip()

        port = _parse_int(
            network.get(
                "port",
                9100,
            ),
            9100,
        )

        return (
            f"Network - {host}:{port}"
            if host
            else "Network - not configured"
        )

    usb = settings.get(
        "usb",
        {},
    )

    return (
        "USB - "
        f"{usb.get('vendor_id', '0x0416')}:"
        f"{usb.get('product_id', '0x5011')}"
    )


def check_printer_connection(settings=None):
    settings = (
        settings
        or load_printer_settings()
    )

    connection = str(
        settings.get(
            "connection",
            "usb",
        )
    ).lower()

    if connection == "network":
        network = settings.get(
            "network",
            {},
        )

        host = str(
            network.get(
                "host",
                "",
            )
        ).strip()

        port = _parse_int(
            network.get(
                "port",
                9100,
            ),
            9100,
        )

        if not host:
            return {
                "ok": False,
                "connection": "network",
                "message": "Network printer host is not configured.",
                "label": printer_connection_label(settings),
            }

        try:
            with socket.create_connection(
                (
                    host,
                    port,
                ),
                timeout=2.0,
            ):
                pass

            return {
                "ok": True,
                "connection": "network",
                "message": "Printer TCP connection succeeded.",
                "label": printer_connection_label(settings),
            }

        except OSError as error:
            return {
                "ok": False,
                "connection": "network",
                "message": str(error),
                "label": printer_connection_label(settings),
            }

    usb = settings.get(
        "usb",
        {},
    )

    vendor_id = _parse_int(
        usb.get(
            "vendor_id",
            "0x0416",
        ),
        0x0416,
    )

    product_id = _parse_int(
        usb.get(
            "product_id",
            "0x5011",
        ),
        0x5011,
    )

    try:
        import usb.core

        device = usb.core.find(
            idVendor=vendor_id,
            idProduct=product_id,
        )

        if device is None:
            return {
                "ok": False,
                "connection": "usb",
                "message": "USB printer was not found.",
                "label": printer_connection_label(settings),
            }

        return {
            "ok": True,
            "connection": "usb",
            "message": "USB printer detected.",
            "label": printer_connection_label(settings),
        }

    except Exception as error:
        return {
            "ok": False,
            "connection": "usb",
            "message": str(error),
            "label": printer_connection_label(settings),
        }


def create_printer(settings=None):
    from escpos.printer import Network, Usb

    settings = (
        settings
        or load_printer_settings()
    )

    connection = str(
        settings.get(
            "connection",
            "usb",
        )
    ).lower()

    if connection == "network":
        network = settings.get(
            "network",
            {},
        )

        host = str(
            network.get(
                "host",
                "",
            )
        ).strip()

        port = _parse_int(
            network.get(
                "port",
                9100,
            ),
            9100,
        )

        if not host:
            raise RuntimeError(
                "Network printer host is not configured."
            )

        return Network(
            host,
            port=port,
        )

    usb = settings.get(
        "usb",
        {},
    )

    return Usb(
        _parse_int(
            usb.get(
                "vendor_id",
                "0x0416",
            ),
            0x0416,
        ),
        _parse_int(
            usb.get(
                "product_id",
                "0x5011",
            ),
            0x5011,
        ),
    )
