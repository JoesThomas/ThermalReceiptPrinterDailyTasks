from __future__ import annotations

import argparse
from datetime import date, datetime

from app import run_live
from config import BASE_DIR, FILES
from health import run_health_checks
from logging_setup import configure_logging
from receipt.model import ReceiptDocument, ReceiptSection
from receipt.renderer import write_preview
from validation import validate_project


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Simulate YYYY-MM-DD instead of today's date.")
    parser.add_argument("--preview", action="store_true", help="Write receipt_preview.txt instead of printing.")
    parser.add_argument("--validate", action="store_true", help="Validate JSON and recipe data, then exit.")
    parser.add_argument("--health", action="store_true", help="Run local health checks, then exit.")
    parser.add_argument("--finance", action="store_true", help="Simulate a finance-requested run.")
    parser.add_argument(
        "--only",
        choices=("information", "actions", "food", "finance"),
        help="Print only one live receipt page for debugging/testing.",
    )
    return parser.parse_args()


def simulated_date(value: str | None) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else date.today()


def build_demo_documents(day: date, finance_requested: bool) -> list[ReceiptDocument]:
    """Offline preview used by --preview; it never calls live services."""
    info = ReceiptDocument("information")
    section = ReceiptSection("date", "DAILY INFORMATION")
    section.add(day.strftime("%A %d %B %Y").upper())
    section.add("Preview mode - live services are not called.")
    info.add(section)

    actions = ReceiptDocument("actions")
    section = ReceiptSection("actions", "DAILY ACTIONS")
    section.add("Calendar / to-do / deliveries render here during a live run.")
    actions.add(section)

    food = ReceiptDocument("food")
    section = ReceiptSection("food", "FOOD")
    section.add("Meal planner uses recipes, cooking rules, equipment and inventory.")
    if day.weekday() == 6:
        section.add("Sunday: prep order + appliance plan + complete mini-recipes.")
    food.add(section)

    documents = [info, actions, food]

    if finance_requested:
        finance = ReceiptDocument("finance")
        section = ReceiptSection("finance", "FINANCE")
        section.add("Finance is printed only when requested in a live run.")
        finance.add(section)
        documents.append(finance)

    return documents


def main():
    args = parse_args()
    logger = configure_logging()

    if args.validate:
        errors = validate_project(FILES)
        if errors:
            print("\n".join(errors))
            raise SystemExit(1)
        print("Validation OK")
        return

    if args.health:
        for result in run_health_checks():
            print(f"{result.name:20} {'OK' if result.ok else 'FAIL':5} {result.detail}")
        return

    day = simulated_date(args.date)

    if args.preview:
        documents = build_demo_documents(day, args.finance)
        path = write_preview(documents, BASE_DIR / "receipt_preview.txt")
        print(f"Preview written to {path}")
        return

    logger.info("Launching modular live receipt pipeline.")
    run_live(
        finance_requested=args.finance,
        only_page=args.only,
    )


if __name__ == "__main__":
    main()
