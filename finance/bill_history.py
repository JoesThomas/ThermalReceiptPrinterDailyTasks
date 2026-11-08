"""Review observed bill variances without altering actual bank payments."""
from hashlib import sha256
import json

from finance.money import parse
from finance.subscription_store import store


def entries(state):
    rows = []
    for frequency in ("monthly", "yearly"):
        for index, bill in enumerate(state.get(frequency, [])):
            for payment in bill.get("history", []):
                if not isinstance(payment, dict):
                    continue
                paid, expected = parse(payment.get("amount")), parse(payment.get("expected"))
                if paid is None or paid <= 0 or expected is None or paid == expected:
                    continue
                key = sha256(json.dumps([frequency, index, bill["name"], payment["date"],
                                        str(expected), str(paid)]).encode()).hexdigest()
                rows.append(dict(key=key, frequency=frequency, bill=bill, payment=payment,
                                 expected=expected, paid=paid, difference=paid - expected))
    return sorted(rows, key=lambda row: row["payment"]["date"], reverse=True)


def decide(path, key, decision):
    if decision not in {"one-off", "recurring"}:
        raise ValueError("Choose one-off or recurring.")

    def change(state):
        row = next((entry for entry in entries(state) if entry["key"] == key), None)
        if row is None or row["payment"].get("decision") != "pending":
            raise ValueError("This payment is no longer awaiting review.")
        if decision == "recurring":
            bill = row["bill"]
            if parse(bill.get("amount")) != row["expected"] or bill.get("last_paid") != row["payment"]["date"]:
                raise ValueError("A newer payment or estimate exists. Use the latest change or edit the commitment.")
            bill["amount"] = float(row["paid"])
        row["payment"]["decision"] = decision
    store(path).update(change)
