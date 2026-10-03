from __future__ import annotations

import os

USB_VENDOR_ID = 0x0416
USB_PRODUCT_ID = 0x5011
DEFAULT_NETWORK_HOST = "192.168.0.220"
DEFAULT_NETWORK_PORT = 9100


class PrinterConnectionError(RuntimeError):
    """The configured physical printer could not be reached."""


def open_printer():
    """Use the local network printer by default; allow USB when requested."""
    from escpos.printer import Network, Usb
    from escpos.exceptions import DeviceNotFoundError

    connection = os.getenv("RECEIPT_PRINTER_CONNECTION", "network").strip().lower()
    if connection == "usb":
        printer = Usb(USB_VENDOR_ID, USB_PRODUCT_ID)
        try:
            printer.cut()
        except Exception:
            printer.close()
            raise
        return printer
    if connection == "network":
        host = os.getenv("RECEIPT_PRINTER_HOST", DEFAULT_NETWORK_HOST).strip()
        port = int(os.getenv("RECEIPT_PRINTER_PORT", str(DEFAULT_NETWORK_PORT)))
        if not host or not 1 <= port <= 65535:
            raise ValueError("Network printer host or port is invalid")
        printer = Network(host, port=port, timeout=10)
        try:
            # Connect before receipt generation; Network otherwise connects lazily.
            printer.open()
            # Separate leftover paper before any new receipt is sent.
            printer.cut()
        except (OSError, DeviceNotFoundError) as error:
            printer.close()
            raise PrinterConnectionError(
                f"Cannot connect to receipt printer at {host}:{port}. "
                "Check its power, Ethernet cable and current IP address. "
                "On your Mac, test the configured address with nc -vz -G 3 HOST PORT. "
                "Set RECEIPT_PRINTER_HOST if its address has changed. "
                "Use python main.py --live-preview to view the receipt without printing."
            ) from error
        return printer
    raise ValueError("RECEIPT_PRINTER_CONNECTION must be 'network' or 'usb'")


def cut(printer) -> None:
    printer.cut()
