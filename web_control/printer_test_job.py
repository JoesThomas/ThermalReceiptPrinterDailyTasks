"""Short physical test, run only through the existing supervised print worker."""
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from receipt.printer import open_printer


def main():
    printer = open_printer()
    try:
        printer.set(align='left')
        printer.text('RECEIPT CONTROL\nPRINTER CONNECTION TEST\n' + datetime.now(ZoneInfo('Europe/London')).strftime('%d %b %Y %H:%M %Z') + '\n\n')
        printer.cut()
    finally: printer.close()


if __name__ == '__main__': main()
