from __future__ import annotations

import os

USB_VENDOR_ID = 0x0416
USB_PRODUCT_ID = 0x5011
DEFAULT_NETWORK_HOST = "192.168.0.220"
DEFAULT_NETWORK_PORT = 9100


def open_printer():
    """Use the local network printer by default; allow USB when requested."""
    from escpos.printer import Network, Usb

    connection = os.getenv("RECEIPT_PRINTER_CONNECTION", "network").strip().lower()
    if connection == "usb":
        return Usb(USB_VENDOR_ID, USB_PRODUCT_ID)
    if connection == "network":
        host = os.getenv("RECEIPT_PRINTER_HOST", DEFAULT_NETWORK_HOST).strip()
        port = int(os.getenv("RECEIPT_PRINTER_PORT", str(DEFAULT_NETWORK_PORT)))
        if not host or not 1 <= port <= 65535:
            raise ValueError("Network printer host or port is invalid")
        return Network(host, port=port, timeout=10)
    raise ValueError("RECEIPT_PRINTER_CONNECTION must be 'network' or 'usb'")


def cut(printer) -> None:
    printer.cut()
