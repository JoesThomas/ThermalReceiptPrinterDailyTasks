from __future__ import annotations

from escpos.printer import Usb

from config import PRINTER


def open_printer() -> Usb:
    return Usb(
        PRINTER["vendor_id"],
        PRINTER["product_id"],
        interface=PRINTER.get("interface", 0),
        in_ep=PRINTER.get("in_ep", 0x82),
        out_ep=PRINTER.get("out_ep", 0x01),
    )


def cut(printer) -> None:
    printer.cut()
