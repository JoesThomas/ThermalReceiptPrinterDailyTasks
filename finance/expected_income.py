"""Private, non-salary expectations; never alter confirmed income or baseline runway."""
from receipt.profile import COLUMNS

from calendar import monthrange
from datetime import date, timedelta
import re
import uuid
from pathlib import Path

from finance.money import parse, ZERO
from finance.projection import occurs, format_runway
from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / "data" / "expected_income.json"
REPEATS = {
    "once": "One-off",
    "monthly": "Monthly",
    "month_end": "Last day of month",
    "yearly": "Yearly",
}


def validate(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"payments"}
        or not isinstance(value["payments"], list)
        or len(value["payments"]) > 100
    ):
        raise ValueError("Invalid expected income data.")
    identities = set()
    for row in value["payments"]:
        if (
            not isinstance(row, dict)
            or not re.fullmatch(r"[a-f0-9]{12}", str(row.get("id", "")))
            or row["id"] in identities
        ):
            raise ValueError("Invalid expected payment.")
        identities.add(row["id"])
        name = row.get("name")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 120
            or any(ord(c) < 32 for c in name)
        ):
            raise ValueError("Enter a payment name up to 120 characters.")
        amount = parse(row.get("amount"), rounded=False)
        if amount is None or not ZERO < amount <= 10000000 or amount != parse(amount):
            raise ValueError("Enter a positive payment amount in pounds and pennies.")
        if row.get("repeat") not in REPEATS or type(row.get("enabled")) is not bool:
            raise ValueError("Choose a supported payment frequency.")
        first = date.fromisoformat(row.get("date", ""))
        end = date.fromisoformat(row["end_date"]) if row.get("end_date") else None
        if end and end < first:
            raise ValueError("End date cannot precede the first payment.")


def store():
    return PrivateStore(FILE, default=lambda: {"payments": []}, validate=validate)


def load():
    return store().read()


def save(values, *, action="save"):
    if action not in {"save", "delete"}:
        raise ValueError("Invalid payment action.")
    identity = values.get("id") or uuid.uuid4().hex[:12]

    def change(state):
        existing = next(
            (row for row in state["payments"] if row["id"] == identity), None
        )
        if values.get("id") and existing is None:
            raise ValueError("Expected payment was not found.")
        rows = [row for row in state["payments"] if row["id"] != identity]
        if action == "save":
            rows.append(
                dict(
                    id=identity,
                    name=values.get("name", "").strip(),
                    amount=values.get("amount", "").strip(),
                    date=values.get("date", ""),
                    repeat=values.get("repeat", "monthly"),
                    end_date=values.get("end_date", ""),
                    enabled=values.get("enabled") == "on",
                )
            )
        state["payments"] = rows

    store().update(change)


def scheduled(rows, today, end):
    """Only future dates: today's bank balance may already contain today's receipts."""
    events = []
    for row in rows:
        if not row["enabled"]:
            continue
        first = date.fromisoformat(row["date"])
        last = (
            min(end, date.fromisoformat(row["end_date"]))
            if row.get("end_date")
            else end
        )
        if row["repeat"] == "once":
            dates = [first]
        else:
            step = 12 if row["repeat"] == "yearly" else 1
            start_month = max(
                0, (today.year - first.year) * 12 + today.month - first.month
            )
            start_index = start_month // step
            count = (
                max(0, (last.year - first.year) * 12 + last.month - first.month) // step
                + 1
            )
            dates = []
            for index in range(start_index, count):
                due = occurs(first, index * step)
                if row["repeat"] == "month_end":
                    due = due.replace(day=monthrange(due.year, due.month)[1])
                dates.append(due)
        for due in dates:
            if today < due <= last and due >= first:
                events.append(
                    dict(
                        id=row["id"],
                        name=row["name"],
                        date=due,
                        amount=parse(row["amount"]),
                    )
                )
    return sorted(events, key=lambda e: (e["date"], e["name"], e["id"]))


def compare(projection, events, today):
    if not projection or not projection["valid"]:
        return {"valid": False}
    incomes, costs = {}, {}
    for event in events:
        incomes[event["date"]] = incomes.get(event["date"], ZERO) + event["amount"]
    for event in projection["events"]:
        costs[event["date"]] = costs.get(event["date"], ZERO) + event["amount"]
    cash = projection["cash"] - projection["buffer"]
    run_out = today if cash < ZERO else None
    low = cash
    timeline = []
    for offset in range(projection["horizon"] + 1):
        on = today + timedelta(days=offset)
        cash += incomes.get(on, ZERO)
        cash -= costs.get(on, ZERO) + (
            projection.get("daily_cost", projection["daily"]) if offset else ZERO
        )
        low = min(low, cash)
        if cash < ZERO and run_out is None:
            run_out = on
        if offset <= 30:
            timeline.append(
                dict(date=on, cash=parse(cash), incoming=incomes.get(on, ZERO))
            )
    return dict(
        valid=True,
        run_out=run_out,
        duration=format_runway((run_out - today).days, today) if run_out else None,
        end=projection["horizon_end_date"],
        end_cash=parse(cash + projection["buffer"]),
        lowest=parse(low + projection["buffer"]),
        timeline=timeline,
    )


def view(projection, today):
    try:
        rows = load()["payments"]
    except (ValueError, OSError, TypeError):
        return {
            "error": "Expected income could not be read. Restore a valid private backup.",
            "rows": [],
            "valid": False,
        }
    end = projection["horizon_end_date"] if projection else today + timedelta(days=1826)
    events = scheduled(rows, today, end)
    next_dates = {}
    for event in events:
        next_dates.setdefault(event["id"], event["date"])
    display = [
        dict(
            row,
            next_date=next_dates.get(row["id"]),
            frequency=REPEATS[row["repeat"]],
        )
        for row in rows
    ]
    days = min(30, projection["horizon"]) if projection else 30
    outlook_end = today + timedelta(days=days)
    upcoming = [event for event in events if event["date"] <= outlook_end]
    outlook = (
        dict(projection, horizon=days, horizon_end_date=outlook_end)
        if projection
        else None
    )
    comparison = compare(outlook, upcoming, today)
    return dict(
        rows=display,
        events=upcoming,
        upcoming=upcoming,
        total=sum((e["amount"] for e in upcoming), ZERO),
        horizon_duration=format_runway(days, today),
        show_end_balance=bool(comparison["valid"] and comparison["run_out"] is None),
        **comparison,
    )


def receipt_summary(projection, today):
    """Short main-finance receipt comparison, keeping the baseline unchanged."""
    from finance.receipt_text import ReceiptText

    result = view(projection, today)
    if result.get("error"):
        return "EXPECTED INCOME UNAVAILABLE\nCheck private expected-income settings.\n"
    if not result["events"]:
        return ""
    page = ReceiptText(width=COLUMNS)
    page.section("EXPECTED INCOME / NO SALARY")
    page.text("Next 30 days; unconfirmed income only.")
    for event in result["upcoming"][:6]:
        page.amount(f"{event['date']:%d %b} {event['name']}", event["amount"])
    if len(result["upcoming"]) > 6:
        page.text(f"+ {len(result['upcoming']) - 6} more; see Finance.")
    page.amount(
        "Expected income / next 30d",
        sum((e["amount"] for e in result["upcoming"]), ZERO),
    )
    if result["valid"]:
        page.text("CASH RUNWAY WITH EXPECTED INCOME")
        page.text(
            result["duration"]
            if result["run_out"]
            else "Over " + result["horizon_duration"]
        )
        if result["run_out"]:
            page.text(f"First shortfall: {result['run_out']:%d %b %Y}")
        else:
            page.text(f"No shortfall through {result['end']:%d %b %Y}")
        if result["show_end_balance"]:
            page.text(f"Projected bank cash {result['end']:%d %b %Y}")
            page.amount("Including expected income", result["end_cash"])
    else:
        page.text(
            "Projection unavailable: complete bank data and spending estimate needed."
        )
    page.text(
        "Same bills, spending and cash buffer. Excludes salary and accessible savings."
    )
    return page.render()
