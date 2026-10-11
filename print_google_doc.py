#!/usr/bin/env python3
"""Standalone Google Doc -> ESC/POS thermal receipt printer."""

import requests
from escpos.printer import Network, Usb


# ==================== CONFIG ====================

GOOGLE_DOC_URL = ""  # Optional explicit override; private settings are read by main().

# "auto" tries USB first, then network.
# You can also force "usb" or "network".
PRINTER_TYPE = "auto"

# Network settings. These are only used if network printing is selected
# (or if auto mode cannot connect by USB).
PRINTER_IP = "192.168.0.220"
PRINTER_PORT = 9100

# USB settings. Replace these with your printer's real USB IDs.
USB_VENDOR_ID = 0x0416
USB_PRODUCT_ID = 0x5011

RECEIPT_WIDTH = 42
PRINT_HEADER = True
HEADER_TEXT = "GOOGLE DOC"
PRINT_FOOTER = True
CUT_AFTER_PRINT = True


# ==================== GOOGLE DOC ====================

def extract_google_doc_id(value):
    from services.google_docs import document_id
    return document_id(value, strict=True)


def download_google_doc_text(value):
    """Download the Google Doc through Google's plain-text export endpoint."""
    document_id = extract_google_doc_id(value)
    from services.google_docs import export_url as document_export_url
    export_url = document_export_url(document_id)

    response = requests.get(export_url, timeout=20)
    response.raise_for_status()

    text = response.text
    if not text.strip():
        raise RuntimeError(
            "Google Doc downloaded successfully but contained no text."
        )

    return text


# ==================== TEXT ====================

from receipt.text import printer_safe_text


def tidy_document_text(text):
    text = printer_safe_text(text)
    lines = [line.rstrip() for line in text.splitlines()]

    output = []
    previous_blank = False

    for line in lines:
        blank = not line.strip()

        if blank and previous_blank:
            continue

        output.append(line)
        previous_blank = blank

    return "\n".join(output).strip()


# ==================== PRINTER ====================

def _connect_usb():
    """Create a USB ESC/POS printer connection."""
    if USB_VENDOR_ID == 0 or USB_PRODUCT_ID == 0:
        raise ValueError(
            "USB printer IDs are not configured."
        )

    return Usb(
        USB_VENDOR_ID,
        USB_PRODUCT_ID,
    )


def _connect_network():
    """Create a network ESC/POS printer connection."""
    if not PRINTER_IP:
        raise ValueError(
            "Network printer IP is not configured."
        )

    return Network(
        PRINTER_IP,
        port=PRINTER_PORT,
        timeout=10,
    )


def connect_printer():
    """
    Connect using USB, network, or automatic fallback.

    PRINTER_TYPE:
        "usb"     - use USB only
        "network" - use network only
        "auto"    - try configured USB first, then network
    """
    printer_type = PRINTER_TYPE.strip().lower()

    if printer_type == "usb":
        print("Using USB printer...")
        return _connect_usb()

    if printer_type == "network":
        print("Using network printer...")
        return _connect_network()

    if printer_type != "auto":
        raise ValueError(
            'PRINTER_TYPE must be "auto", "usb", or "network".'
        )

    errors = []

    # Prefer USB when IDs have been configured.
    if USB_VENDOR_ID != 0 and USB_PRODUCT_ID != 0:
        try:
            print("Trying USB printer...")
            printer = _connect_usb()

            # Accessing the device forces python-escpos to open it now,
            # so a USB failure can fall through to network mode.
            _ = printer.device

            print("Connected by USB.")
            return printer

        except Exception as error:
            errors.append(
                f"USB: {error!r}"
            )
            print("USB connection unavailable.")

    # Then try network if an IP has been configured.
    if PRINTER_IP:
        try:
            print("Trying network printer...")
            printer = _connect_network()

            # Force the lazy network connection to open now.
            _ = printer.device

            print("Connected by network.")
            return printer

        except Exception as error:
            errors.append(
                f"Network: {error!r}"
            )
            print("Network connection unavailable.")

    details = "\n".join(errors)

    raise RuntimeError(
        "Could not connect to the thermal printer by USB "
        "or network."
        + (f"\n{details}" if details else "")
    )


def print_separator(printer):
    printer.text("-" * RECEIPT_WIDTH + "\n")


def print_document(printer, document_text):
    if PRINT_HEADER:
        printer.set(
            align="center",
            bold=True,
            width=1,
            height=1,
        )
        printer.text(printer_safe_text(HEADER_TEXT) + "\n")

        printer.set(
            align="left",
            bold=False,
            width=1,
            height=1,
        )
        print_separator(printer)

    printer.set(
        align="left",
        bold=False,
        width=1,
        height=1,
    )
    printer.text(document_text + "\n")

    if PRINT_FOOTER:
        print_separator(printer)
        printer.set(
            align="center",
            bold=False,
            width=1,
            height=1,
        )
        printer.text("END OF DOCUMENT\n")

    printer.text("\n\n\n")

    if CUT_AFTER_PRINT:
        printer.cut()


# ==================== MAIN ====================

def main():
    document_url = GOOGLE_DOC_URL
    if not document_url:
        from services.private_config import load, value
        document_url = value(load(), 'google_docs', 'to_buy_url')
    if (
        not document_url
        or document_url == "PASTE_GOOGLE_DOC_URL_HERE"
    ):
        raise ValueError(
            "Set GOOGLE_DOC_URL at the top of this file first."
        )

    print("Downloading Google Doc...")
    document_text = download_google_doc_text(document_url)
    document_text = tidy_document_text(document_text)

    print("Connecting to thermal printer...")
    printer = connect_printer()

    try:
        print_document(printer, document_text)
        print("Google Doc printed successfully.")
    finally:
        close_method = getattr(printer, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nPrinting cancelled.")
    except Exception as error:
        print("\nPrinting failed:")
        print(repr(error))
        raise
