"""Short physical test, run only through the existing supervised print worker."""

import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from receipt.printer import open_printer


def main():
    paper_test = "--paper-test" in sys.argv[1:]
    printer = open_printer(initial_cut=False) if paper_test else open_printer()
    try:
        printer.set(align="left")
        now = datetime.now(ZoneInfo("Europe/London"))
        if paper_test:
            printer.text(
                "PAPER FEED TEST\n"
                "      _\n"
                "     /(|\n"
                "    (  :\n"
                "  __\\  \\  _____\n"
                " (____)  `|\n"
                " (____)|   |\n"
                " (____).__|\n"
                "  (___)__.|_____\n"
            )
        else:
            printer.text(
                "RECEIPT CONTROL\nPRINTER CONNECTION TEST\n"
                + now.strftime("%d %b %Y %H:%M %Z")
                + "\n\n"
            )
        printer.cut()
    finally:
        printer.close()


if __name__ == "__main__":
    main()
