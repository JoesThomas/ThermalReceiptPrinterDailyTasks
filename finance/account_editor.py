"""One validated editor for existing accounts, retaining their canonical identity."""

from datetime import date
from decimal import Decimal
from finance import savings_goals as goals, wealth_history
from storage import write_bytes


def save(account, values, wealth, today):
    known = goals.review(wealth, on=today)["accounts"]
    current = next((row for row in known if row["id"] == account), None)
    if current is None:
        raise ValueError("Choose a recorded account.")
    label = values.get("display_name", "").strip()
    if len(label) > 90 or any(ord(c) < 32 for c in label):
        raise ValueError("Use a display name up to 90 characters.")
    if label and any(
        row["id"] != account
        and row["kind"] == current["kind"]
        and label.casefold()
        in {row["name"].casefold(), row.get("label", row["name"]).casefold()}
        for row in known
    ):
        raise ValueError("Another account already uses that name.")
    kind = values.get("type", "")
    if kind not in goals.TYPES:
        raise ValueError("Choose a valid account type.")

    def optional(key):
        raw = values.get(key, "").strip()
        return str(wealth_history.amount(raw)) if raw else None

    target, limit, share = (
        optional("target"),
        optional("balance_limit"),
        optional("monthly_share"),
    )
    if target is not None and Decimal(target) <= 0:
        raise ValueError("A target must be positive, or blank.")
    if kind == "premium_bonds" and target is not None and Decimal(target) > 50000:
        raise ValueError("Premium Bonds target cannot exceed £50,000.")
    rate = optional("interest_rate") if kind in {"savings", "cash_isa"} else None
    effective = (
        date.fromisoformat(values.get("rate_date", "")).isoformat()
        if rate is not None
        else None
    )
    if effective and date.fromisoformat(effective).year < 2000:
        raise ValueError("Choose a valid interest effective date.")
    balance = values.get("balance", "").strip()
    stamp = values.get("balance_date", "").strip()
    if balance:
        balance = wealth_history.amount(balance)
        on = date.fromisoformat(stamp)
        if on > today or on.year < 2000:
            raise ValueError("Choose a balance date no later than today.")
    # Hold the existing history writer lock and roll back history if settings cannot be saved.
    with wealth_history._LOCK:
        history = wealth_history.HISTORY_FILE
        before = history.read_bytes() if history.exists() else None
        recorded = False
        try:
            with goals.edit() as state:
                old = state["accounts"].get(account, {})
                row = dict(
                    old,
                    name=current["name"],
                    kind=current["kind"],
                    type=kind,
                    display_name=label or None,
                    target=target,
                    balance_limit=limit,
                    monthly_share=share or "0",
                    interest_rate=rate,
                )
                if effective:
                    row["rate_date"] = effective
                else:
                    row.pop("rate_date", None)
                state["accounts"][account] = row
                if old.get("type") != kind:
                    for year in state["years"].values():
                        year["complete"] = False
                goals.validate(state)
                if balance != "":
                    existing = next(
                        (
                            r
                            for r in wealth_history.load_history()
                            if r["kind"] == current["kind"]
                            and r["name"].casefold() == current["name"].casefold()
                            and r["date"] == stamp
                        ),
                        {},
                    )
                    wealth_history.record(
                        current["name"],
                        current["kind"],
                        stamp,
                        balance,
                        deposits=existing.get("deposits"),
                        withdrawals=existing.get("withdrawals"),
                        today=today,
                    )
                    recorded = True
        except Exception:
            if recorded:
                if before is None:
                    history.unlink(missing_ok=True)
                else:
                    write_bytes(history, before)
            raise
