"""Illustrative full-width receipt pages before a captured web print exists."""
from __future__ import annotations
from receipt.profile import COLUMNS

from datetime import date


def example_pages(today: date):
    stamp = today.strftime("%a %d %b %Y").upper()
    pages = {
        "information": (
            "==========================================\n"
            "       DAILY INFORMATION · SAMPLE         \n"
            "==========================================\n"
            f"{stamp}\n"
            "STIRCHLEY, BIRMINGHAM\n"
            "------------------------------------------\n"
            "WEATHER                18C  CLOUDY\n"
            "NOW    18C  |=========\n"
            "12:00  20C  |===========\n"
            "16:00  19C  |==========\n"
            "20:00  16C  |=======\n"
            "------------------------------------------\n"
            "NEWS\n"
            "  1. Example headline on today's receipt\n"
            "LOCAL NEWS\n"
            "  1. Example Birmingham story\n"
            "SPORT\n"
            "  1. Example sport story\n"
        ),
        "actions": (
            "==========================================\n"
            "           DAILY ACTIONS · SAMPLE         \n"
            "==========================================\n"
            "TODAY'S CALENDAR\n"
            "  11:00  Example appointment\n"
            "------------------------------------------\n"
            "TO-DO\n"
            "  [ ] Example task\n"
            "  [ ] Food shop\n"
            "------------------------------------------\n"
            "DELIVERIES\n"
            "  No example deliveries\n"
        ),
        "food": (
            "==========================================\n"
            "            FOOD / MEAL · SAMPLE          \n"
            "==========================================\n"
            "TODAY'S RECIPE\n"
            "  Example dinner · 30 MIN · SERVES 1\n"
            "------------------------------------------\n"
            "INGREDIENTS\n"
            "  [ ] Example ingredient\n"
            "METHOD\n"
            "  1. Follow the printed recipe steps.\n"
            "------------------------------------------\n"
            "MEAL SHOPPING LIST\n"
            "  [ ] Example shopping item\n"
        ),
        "finance": (
            "==========================================\n"
            "              FINANCE · SAMPLE            \n"
            "==========================================\n"
            "BANK BALANCES                     [B]\n"
            "  Example account           £100.00\n"
            "------------------------------------------\n"
            "SPENDING BY CATEGORY (30 DAYS)\n"
            "  Food                       £25.00\n"
            "  Transport                  £10.00\n"
            "------------------------------------------\n"
            "MONTHLY COMMITMENTS [F+B]\n"
            "PAID [BANK MATCH]\n"
            "  Example bill               £15.00\n"
            "DUE [FILE / NO BANK MATCH]\n"
            "  Example plan               £20.00\n"
            "REMAINING                   £20.00\n"
            "==========================================\n"
        ),
    }

    titles = {"NEWS", "LOCAL NEWS", "SPORT", "TODAY'S CALENDAR", "TO-DO", "DELIVERIES", "TODAY'S RECIPE", "INGREDIENTS", "METHOD", "MEAL SHOPPING LIST", "SPENDING BY CATEGORY (30 DAYS)", "MONTHLY COMMITMENTS [F+B]"}
    for name, text in pages.items():
        rows = []
        for row in text.splitlines():
            if row and set(row) <= {"-", "="}:
                row = row[0] * COLUMNS
            elif row.strip() in titles or '· SAMPLE' in row:
                row = row.strip().center(COLUMNS)
            rows.append(row)
        pages[name] = "\n".join(rows) + "\n"
    return pages
