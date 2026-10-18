"""Two successful finance checkpoints; views never write or fetch bank data."""

from pathlib import Path
from datetime import date, datetime, timedelta
from finance.money import parse, format_pounds
from finance.savings_goals import identity
from storage import PrivateStore

FILE = Path(__file__).resolve().parents[1] / "data" / "finance_check_changes.json"


def validate(state):
    if not isinstance(state, dict) or set(state) - {
        "previous",
        "current",
        "changes",
        "checked_at",
    }:
        raise ValueError("Invalid finance check comparison.")
    for key in ("previous", "current"):
        row = state.get(key)
        if row is None:
            continue
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("accounts"), dict)
            or not isinstance(row.get("bills"), list)
        ):
            raise ValueError("Invalid finance checkpoint.")
        if (
            type(row.get("valid")) is not bool
            or len(row["accounts"]) > 500
            or len(row["bills"]) > 2000
            or any(not isinstance(b, str) or len(b) > 1000 for b in row["bills"])
        ):
            raise ValueError("Invalid finance checkpoint details.")
        if row.get("shortfall") is not None:
            date.fromisoformat(row["shortfall"])
        for field in ("cash", "debt"):
            if row.get(field) is not None and parse(row[field]) is None:
                raise ValueError("Invalid finance amount.")
        for account in row["accounts"].values():
            if (
                not isinstance(account, dict)
                or not isinstance(account.get("name"), str)
                or parse(account.get("balance")) is None
            ):
                raise ValueError("Invalid savings checkpoint.")
    if state.get("checked_at"):
        timestamp = datetime.fromisoformat(state["checked_at"])
        if timestamp.tzinfo is None:
            raise ValueError("Invalid finance check time.")
    if not isinstance(state.get("changes", []), list) or any(
        not isinstance(x, str) for x in state.get("changes", [])
    ):
        raise ValueError("Invalid finance changes.")


def store():
    return PrivateStore(FILE, default=dict, validate=validate)


def view():
    try:
        return store().read()
    except (ValueError, OSError):
        return {"error": "Finance comparison unavailable; check the private data."}


def record(model, stamp, today):
    p = model["projection"]
    summary = model["observation"]["summary"]
    if summary.get("bank_data_status") != "complete" or p.get("cash") is None:
        return
    wealth = model.get("wealth") or {}
    labels = {
        r["id"]: r.get("label", r["name"])
        for r in (model.get("goals") or {}).get("accounts", [])
    }
    current = dict(
        cash=str(p["cash"]),
        debt=str(model["insights"]["observation"]["card_debt"])
        if model["insights"]["observation"]["card_debt"] is not None
        else None,
        accounts={
            identity(r["name"], r["kind"]): dict(
                name=labels.get(identity(r["name"], r["kind"]), r["name"]),
                balance=str(r["balance"]),
            )
            for r in wealth.get("accounts", [])
        },
        bills=[
            f"{e['date'].isoformat()} | {e['name']} | {e['amount']}"
            for e in p["events"]
            if today <= e["date"] <= today + timedelta(days=30)
        ],
        shortfall=p.get("cash_run_out_date").isoformat()
        if p.get("cash_run_out_date")
        else None,
        scope=dict(
            transactions=summary.get("collection_scope"),
            cash_accounts={
                provider: dict(
                    scope=row.get("scope"),
                    names=[part.get("name") for part in row.get("accounts", [])],
                )
                for provider, row in model.get("snapshot", {})
                .get("balances", {})
                .items()
                if provider in {"HSBC", "MONZO"}
            },
        ),
        valid=p["valid"],
    )

    def change(state):
        previous = state.get("current")
        lines = []
        if previous and previous.get("scope") == current.get("scope"):
            for field, label in [("cash", "Bank cash"), ("debt", "Amex owed")]:
                if current[field] is not None and previous.get(field) is not None:
                    delta = parse(current[field]) - parse(previous[field])
                    if delta:
                        lines.append(
                            f"{label}: {'+' if delta > 0 else ''}{format_pounds(delta)} since the previous check."
                        )
            for key, row in current["accounts"].items():
                old = previous["accounts"].get(key)
                if old is None:
                    lines.append("New recorded account: " + row["name"])
                elif delta := parse(row["balance"]) - parse(old["balance"]):
                    lines.append(
                        f"{row['name']}: {'+' if delta > 0 else ''}{format_pounds(delta)} recorded balance change."
                    )
            added = [b for b in current["bills"] if b not in previous["bills"]]
            lines.extend("New or changed upcoming payment: " + b for b in added[:10])
        elif previous:
            lines.append(
                "Bank source selection changed; balance differences are not directly comparable."
            )
        state.clear()
        state.update(
            previous=previous, current=current, changes=lines, checked_at=stamp
        )

    store().update(change)
