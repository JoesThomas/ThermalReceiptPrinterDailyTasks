"""Bounded monthly planning ledgers. Returns are assumptions, never bill funding."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from finance.money import rounded
from finance.projection import occurs
from finance.long_range.config import validate, number

D = Decimal
ZERO = D(0)
ISA = {"cash_isa", "stocks_isa"}
INVEST = {"stocks_isa", "investment", "pension", "property"}


def month_index(on):
    return on.year * 12 + on.month


def run(
    raw,
    case="expected",
    *,
    missed_salary=False,
    late_salary=False,
    extra_monthly=ZERO,
    details=True,
):
    v = validate(raw)
    start = date.fromisoformat(v["start"])
    end = occurs(start, int(v["years"]) * 12) - timedelta(days=1)
    count = int(v["years"]) * 12 + (start.day > 1)
    rows = deepcopy(v["accounts"])
    by_id = {a["id"]: a for a in rows}
    banks = [a for a in rows if a["kind"] == "bank"]
    for a in rows:
        for k in (
            "balance",
            "target",
            "monthly",
            "fee",
            "tax",
            "yield_rate",
            "apr",
            "isa_used",
        ):
            a[k] = number(a[k])
        a["limit"] = number(a["limit"]) if a["limit"] else None
        a["rate"] = number(a[case], -50, 50)
        a["value"] = a["balance"]
        a["contingent"] = ZERO
        a["factor"] = (1 + a["rate"] / 100) ** (D(1) / 12)
        a["cohorts"] = [(-2, a["balance"])] if a["kind"] == "premium_bonds" else []
    salary = number(v["salary"])
    other = number(v["other_income"])
    spend = number(v["spending"])
    bills = number(v["bills"])
    inflation = 1 + number(v["inflation"], -20, 30) / 100
    income_factor = (1 + number(v["income_growth"], -20, 30) / 100) ** (D(1) / 12)
    spend_factor = (1 + number(v["spending_growth"], -20, 30) / 100) ** (D(1) / 12)
    floor = number(v["minimum"])
    allowance = number(v["isa_allowance"])
    cash_allowance = number(v["cash_isa_limit"])
    used = {}
    cash_used = {}
    first_year = start.year - (start.month < 4 or (start.month == 4 and start.day < 6))
    used[first_year] = sum((a["isa_used"] for a in rows if a["kind"] in ISA), ZERO)
    cash_used[first_year] = sum(
        (a["isa_used"] for a in rows if a["kind"] == "cash_isa"), ZERO
    )
    points = []
    goals = {}
    first_breach = None
    payout_cash = ZERO
    deferred_salary = ZERO

    def bank_value():
        return sum((a["value"] for a in banks), ZERO)

    def take(amount, *, protected=True):
        amount = max(ZERO, amount)
        if protected:
            amount = min(amount, max(ZERO, bank_value() - floor))
        left = amount
        for b in banks:
            part = min(max(ZERO, b["value"]), left)
            b["value"] -= part
            left -= part
            ledger[b["id"]]["transfers_out"] += part
        if left:
            banks[0]["value"] -= left
            ledger[banks[0]["id"]]["transfers_out"] += left
        return amount

    def room(a, on):
        cap = a["limit"]
        if a["kind"] == "premium_bonds":
            cap = min(cap, D(50000)) if cap is not None else D(50000)
        if a["stop"] and a["target"] > 0:
            cap = min(cap, a["target"]) if cap is not None else a["target"]
        available = max(ZERO, cap - a["value"]) if cap is not None else D("1e50")
        year = on.year - (on.month < 4 or (on.month == 4 and on.day < 6))
        if v["isa_enabled"] and a["kind"] in ISA:
            available = min(available, max(ZERO, allowance - used.get(year, ZERO)))
            if a["kind"] == "cash_isa":
                available = min(
                    available, max(ZERO, cash_allowance - cash_used.get(year, ZERO))
                )
        return max(ZERO, available)

    def deposit(
        a, amount, on, index, ledger, *, contingent=False, reinvested_prize=False
    ):
        part = min(max(ZERO, amount), room(a, on))
        a["value"] += part
        ledger[a["id"]]["transfers_in"] += part
        if contingent:
            a["contingent"] += part
        if a["kind"] == "premium_bonds" and part:
            a["cohorts"].append((index - 1 if reinvested_prize else index, part))
        year = on.year - (on.month < 4 or (on.month == 4 and on.day < 6))
        if a["kind"] in ISA:
            used[year] = used.get(year, ZERO) + part
            if a["kind"] == "cash_isa":
                cash_used[year] = cash_used.get(year, ZERO) + part
        return part

    for index in range(count):
        # Calendar month-end, including the first partial month.
        first = date(start.year, start.month, 1)
        on = min(occurs(first, index + 1) - timedelta(days=1), end)
        period_start = max(start, occurs(first, index))
        days = (on - period_start).days + 1
        fraction = D(days) / D((occurs(first, index + 1) - occurs(first, index)).days)
        ledger = {
            a["id"]: dict(
                opening=a["value"],
                transfers_in=ZERO,
                transfers_out=ZERO,
                interest=ZERO,
                growth=ZERO,
                prizes=ZERO,
                fees=ZERO,
                tax=ZERO,
                closing=ZERO,
            )
            for a in rows
        }
        lumps = ZERO
        costs = ZERO
        notes = []
        withdrawals = []
        for event in v["events"]:
            event_on = date.fromisoformat(event["date"])
            delta = month_index(on) - month_index(event_on)
            if delta < 0 or (
                delta > 0 and (not int(event["repeat"]) or delta % int(event["repeat"]))
            ):
                continue
            amount = number(event["amount"])
            kind = event["kind"]
            notes.append(event["name"])
            if kind == "salary":
                salary = amount
            elif kind == "other_income":
                other = amount
            elif kind == "spending":
                spend = amount
            elif kind == "bills":
                bills = amount
            elif kind == "income":
                lumps += amount
            elif kind == "cost":
                costs += amount * (inflation ** (D(index) / 12))
            elif kind == "contribution":
                by_id[event["account"]]["monthly"] = amount
            elif kind == "realise_payout":
                realised = min(amount, payout_cash)
                payout_cash -= realised
                lumps += realised
            elif kind == "asset_purchase":
                a = by_id[event["account"]]
                if a["kind"] != "property":
                    raise ValueError(
                        "Use asset purchase for a property / illiquid asset; use contributions for financial accounts."
                    )
                take(amount, protected=False)
                a["value"] += amount
                ledger[a["id"]]["transfers_in"] += amount
            elif kind == "withdraw":
                withdrawals.append(
                    (by_id[event["account"]], amount, occurs(event_on, delta))
                )
        active_salary = salary
        if (missed_salary or late_salary) and index == 0:
            if late_salary:
                deferred_salary = active_salary * fraction
            active_salary = ZERO
        income = (active_salary + other) * fraction
        if late_salary and index == 1:
            income += deferred_salary
        banks[0]["value"] += income + lumps
        ledger[banks[0]["id"]]["transfers_in"] += income + lumps
        for a, amount, withdrawal_date in withdrawals:
            if a["kind"] in ("bank", "debt") or (
                a["unlock"] and date.fromisoformat(a["unlock"]) > withdrawal_date
            ):
                notes.append("Withdrawal blocked: " + a["name"])
                continue
            part = min(a["value"], amount)
            a["value"] -= part
            if a["kind"] == "premium_bonds":
                remaining = part
                cohorts = []
                for bought, held in sorted(a["cohorts"]):
                    removed = min(held, remaining)
                    remaining -= removed
                    if held > removed:
                        cohorts.append((bought, held - removed))
                a["cohorts"] = cohorts
            # An explicit withdrawal realises the modelled return; apply configured flat tax.
            tax = (
                part * a["tax"] / 100
                if a["kind"] not in ISA | {"premium_bonds"}
                else ZERO
            )
            ledger[a["id"]]["tax"] += tax
            ledger[a["id"]]["transfers_out"] += part - tax
            banks[0]["value"] += part - tax
            ledger[banks[0]["id"]]["transfers_in"] += part - tax
            a["contingent"] = min(a["contingent"], a["value"])
        owed = bank_value() < 0 or any(
            a["kind"] == "debt" and "amex" in a["name"].lower() and a["value"] > 0
            for a in rows
        )
        spending = (
            bills + (min(spend, number(v["debt_spending"])) if owed else spend)
        ) * fraction + costs
        take(spending, protected=False)
        # Interest and regular debt payments are bills; extra repayments use protected spare cash.
        for a in rows:
            if a["kind"] != "debt":
                continue
            interest = a["value"] * a["apr"] / 1200 * fraction
            a["value"] += interest
            ledger[a["id"]]["interest"] += interest
            payment = min(a["value"], a["monthly"] * fraction)
            take(payment, protected=False)
            a["value"] -= payment
            ledger[a["id"]]["transfers_out"] += payment
        for a in rows:
            if a["scheduled"] and a["kind"] not in ("bank", "debt", "property"):
                paid = deposit(a, a["monthly"] * fraction, on, index, ledger)
                take(paid, protected=False)
        room_after_bills = max(ZERO, bank_value() - floor)
        debt_order = sorted(
            (
                a
                for a in rows
                if a["kind"] == "debt" and (a["early"] or "amex" in a["name"].lower())
            ),
            key=lambda a: (0 if "amex" in a["name"].lower() else 1, a["value"]),
        )
        for a in debt_order:
            amount = a["value"]
            if "amex" in a["name"].lower():
                amount = min(amount, room_after_bills)
            if amount <= room_after_bills:
                paid = take(amount)
                a["value"] -= paid
                room_after_bills -= paid
                ledger[a["id"]]["transfers_out"] += paid
        # Bank targets are retained cash, not another expense or asset.
        reserve_target = max(floor, sum((a["target"] for a in banks), ZERO))
        # Rebalance only through explicit ledger entries at the allocation step.
        for b in banks[1:]:
            part = min(
                max(ZERO, b["target"] - b["value"]),
                max(ZERO, banks[0]["value"] - banks[0]["target"]),
            )
            banks[0]["value"] -= part
            b["value"] += part
            ledger[banks[0]["id"]]["transfers_out"] += part
            ledger[b["id"]]["transfers_in"] += part
        extra = max(ZERO, bank_value() - reserve_target)
        candidates = [a for a in rows if a["kind"] not in ("bank", "property", "debt")]
        # Physical cash top-ups precede extra investments.
        for a in candidates:
            if a["kind"] != "cash":
                continue
            amount = min(extra, max(ZERO, a["target"] - a["value"]))
            paid = deposit(a, amount, on, index, ledger)
            take(paid)
            extra -= paid
        if (active_salary > 0 or v["invest_without_salary"]) and not any(
            a["kind"] == "debt"
            and (a["early"] or "amex" in a["name"].lower())
            and a["value"] > 0
            for a in rows
        ):
            for a in candidates:
                if a["kind"] == "cash" or a["scheduled"]:
                    continue
                amount = min(extra, a["monthly"] * fraction + extra_monthly)
                paid = deposit(a, amount, on, index, ledger)
                take(paid)
                extra -= paid
            if active_salary > 0 or v["invest_without_salary"]:
                eligible = [
                    a
                    for a in candidates
                    if a["kind"] != "cash" and a["extra"] and room(a, on) > 0
                ]
                for _ in range(len(eligible) + 1):
                    if not eligible or extra < D(".01"):
                        break
                    share = extra / len(eligible)
                    moved = ZERO
                    for a in eligible:
                        paid = deposit(a, share, on, index, ledger)
                        take(paid)
                        moved += paid
                    extra -= moved
                    eligible = [a for a in eligible if room(a, on) > D(".001")]
                    if moved < D(".001"):
                        break
        # Returns occur at month end; payouts never finance this or future bills implicitly.
        payouts = []
        for a in rows:
            if a["kind"] in ("debt", "cash"):
                continue
            opening = ledger[a["id"]]["opening"]
            closing_before = a["value"]
            # Growth uses remaining opening capital; new allocations are month-end deposits.
            principal = max(
                ZERO,
                opening - ledger[a["id"]]["transfers_out"] - ledger[a["id"]]["tax"],
            )
            rate = a["rate"]
            growth = ZERO
            prize = ZERO
            yield_amount = ZERO
            if a["kind"] == "premium_bonds":
                eligible = min(
                    a["value"],
                    sum(
                        (
                            amount
                            for bought, amount in a["cohorts"]
                            if bought <= index - 2
                        ),
                        ZERO,
                    ),
                )
                prize = eligible * rate / 1200 * fraction
                ledger[a["id"]]["prizes"] += prize
                payouts.append((a, prize, True))
            else:
                growth = principal * ((1 + rate / 100) ** (D(days) / 365) - 1)
                if a["kind"] in INVEST:
                    ledger[a["id"]]["growth"] += growth
                else:
                    ledger[a["id"]]["interest"] += growth
                yield_amount = min(
                    max(ZERO, principal + growth),
                    principal * a["yield_rate"] / 1200 * fraction,
                )
                if yield_amount:
                    growth -= yield_amount
                    payouts.append((a, yield_amount, False))
                a["value"] += growth
                if a["kind"] in INVEST:
                    a["contingent"] += max(ZERO, growth)
            fee = closing_before * a["fee"] / 1200 * fraction
            tax = (
                max(ZERO, growth + yield_amount) * a["tax"] / 100
                if a["kind"] not in ISA | {"premium_bonds", "pension"}
                else ZERO
            )
            a["value"] = (
                a["value"] - fee - tax
                if a["kind"] == "bank"
                else max(ZERO, a["value"] - fee - tax)
            )
            ledger[a["id"]]["fees"] += fee
            ledger[a["id"]]["tax"] += tax
        for a, amount, is_prize in payouts:
            if amount <= 0:
                continue
            destination = a["payout"]
            ledger[a["id"]]["transfers_out"] += amount
            if destination == "self":
                destination = a["id"]
            paid = ZERO
            if destination in by_id and by_id[destination]["kind"] != "bank":
                target = by_id[destination]
                # Growth inside an ISA is not a new subscription; cross-account payouts are.
                if target is a and not is_prize:
                    target["value"] += amount
                    paid = amount
                    ledger[a["id"]]["transfers_out"] -= amount
                else:
                    paid = deposit(
                        target,
                        amount,
                        on,
                        index,
                        ledger,
                        contingent=True,
                        reinvested_prize=is_prize and target is a,
                    )
                    if target is a:
                        ledger[a["id"]]["transfers_in"] -= paid
                        ledger[a["id"]]["transfers_out"] -= paid
            payout_cash += amount - paid
            if amount > paid:
                notes.append("Assumed payout held separately: " + a["name"])
        totals = {k: ZERO for k in ("accessible", "locked", "debts")}
        for a in rows:
            ledger[a["id"]]["closing"] = a["value"]
            if a["kind"] == "debt":
                totals["debts"] += a["value"]
            elif a["kind"] == "bank" and a["value"] < 0:
                totals["debts"] -= a["value"]
            elif a["kind"] == "property" or (
                a["kind"] == "pension" and date.fromisoformat(a["unlock"]) > on
            ):
                totals["locked"] += a["value"]
            else:
                totals["accessible"] += a["value"]
            if a["target"] and a["value"] >= a["target"] and a["id"] not in goals:
                goals[a["id"]] = on
        breach = bank_value() < floor - D(".005")
        if breach and first_breach is None:
            first_breach = on
        net = totals["accessible"] + totals["locked"] + payout_cash - totals["debts"]
        points.append(
            dict(
                date=on,
                fraction=fraction,
                bank=bank_value(),
                income=income + lumps,
                spending=spending,
                debts=totals["debts"],
                accessible=totals["accessible"],
                locked=totals["locked"],
                payout_cash=payout_cash,
                net_worth=net,
                real_worth=net / (inflation ** (D((on - start).days + 1) / 365)),
                unallocated=max(ZERO, bank_value() - reserve_target),
                breach=breach,
                notes=notes,
                accounts=deepcopy(ledger)
                if details
                else {
                    key: {"closing": value["closing"]} for key, value in ledger.items()
                },
            )
        )
        salary *= income_factor**fraction
        other *= income_factor**fraction
        spend *= spend_factor**fraction
        bills *= spend_factor**fraction
    goal_results = []
    for goal in v["goals"]:
        wanted = number(goal["amount"])
        due = date.fromisoformat(goal["date"])
        idx = max((i for i, p in enumerate(points) if p["date"] <= due), default=-1)
        if goal["inflates"]:
            wanted *= inflation ** (D((due - start).days) / 365)
        value = (
            points[idx]["accounts"][goal["account"]]["closing"]
            if idx >= 0
            else by_id[goal["account"]]["balance"]
        )
        account = by_id[goal["account"]]
        is_debt = account["kind"] == "debt"
        annual = (
            account["apr"]
            if is_debt
            else account["rate"]
            if account["kind"] != "premium_bonds"
            else ZERO
        )
        annual = (
            annual
            * (
                1 - account["tax"] / 100
                if account["kind"] not in ISA | {"pension"} and annual > 0
                else 1
            )
            - account["fee"]
        )
        factor = (1 + annual / 100) ** (D(1) / 12)
        annuity = sum(
            (points[j]["fraction"] * factor ** (idx - j) for j in range(idx + 1)), ZERO
        )
        shortfall = max(ZERO, value - wanted) if is_debt else max(ZERO, wanted - value)
        needed = shortfall / annuity if annuity else shortfall
        cap = account["limit"]
        if account["kind"] == "premium_bonds":
            cap = min(cap, D(50000)) if cap is not None else D(50000)
        if account["stop"] and account["target"]:
            cap = min(cap, account["target"]) if cap is not None else account["target"]
        limit_blocked = not is_debt and cap is not None and wanted > cap
        reached = next(
            (
                p["date"]
                for p in points
                if (
                    p["accounts"][goal["account"]]["closing"] <= number(goal["amount"])
                    if is_debt
                    else p["accounts"][goal["account"]]["closing"]
                    >= number(goal["amount"])
                    * (
                        inflation ** (D((p["date"] - start).days) / 365)
                        if goal["inflates"]
                        else 1
                    )
                )
            ),
            None,
        )
        # Zero-return contribution shortfall is conservative, not an optimised investment promise.
        goal_results.append(
            dict(
                name=goal["name"],
                due=due,
                target=wanted,
                projected=value,
                shortfall=shortfall,
                extra_monthly=needed,
                as_of=points[idx]["date"] if idx >= 0 else start,
                lump_required=idx < 0,
                locked_until=account["unlock"]
                if account["kind"] == "pension"
                and date.fromisoformat(account["unlock"]) > due
                else None,
                limit_blocked=limit_blocked,
                affordable=not limit_blocked
                and idx >= 0
                and all(needed <= p["unallocated"] for p in points[: idx + 1]),
                reached=reached,
            )
        )
    return dict(
        case=case,
        points=points,
        goals=goal_results,
        account_goals=goals,
        first_breach=first_breach,
        final=points[-1],
        years=int(v["years"]),
        name=v["name"],
    )
