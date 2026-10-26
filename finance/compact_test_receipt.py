"""Action-first summary of an existing forecast; never recalculates allocations."""

from decimal import Decimal
from finance.money import format_pounds
from finance.projection import money
from finance.receipt_text import ReceiptText
from finance.test_forecast import is_card_payment

ZERO = Decimal(0)


def receipt(result, today):
    page = ReceiptText()
    text, amount, section = page.text, page.amount, page.section
    data, base, forecast = result["inputs"], result["projection"], result["forecast"]
    first = forecast["payments"][0]
    accounts = result["account_plan"]["accounts"] if data["use_accounts"] else []
    reserve = base.get("reserve_details") or {}
    strategies = {
        "amex_first": "Amex first",
        "savings_first": "Savings first",
        "split": f"Split: {data['split'].normalize():f}% to Amex",
    }

    def name(row):
        return row.get("label", row["name"])

    def duration(on):
        if on <= today:
            return "Now"
        months = (
            (on.year - today.year) * 12 + on.month - today.month + (on.day > today.day)
        )
        return f"About {months} " + ("month" if months == 1 else "months")

    def target_date(on, extended=False, label="Projected target date:"):
        if extended:
            text("Not reached within selected forecast.")
        text(f"{label} around {on:%B %Y}")
        text("Estimated time to target: " + duration(on))
        if extended:
            text("Beyond selected forecast; same pathway.")

    section("TEST FINANCE")
    text(
        "SIMULATION - LUMP SUM ONLY"
        if data["mode"] == "lump"
        else "SIMULATION - POTENTIAL SALARY"
    )
    text(f"Forecast: {data['start']:%d %b %Y} to {forecast['end']:%d %b %Y}")
    text(f"Generated {today:%d %b %Y}")
    text("Strategy: " + strategies[data["strategy"]])
    if data["mode"] != "lump":
        amount("Monthly salary when active", data["salary"] + data["existing"])
        if first["salary"] != data["salary"] + data["existing"]:
            amount("Salary this payday", first["salary"])
    if first.get('spending_limited'):
        amount('Debt/overdraft spending ceiling', first['spending_cap'])
        text('Monthly maximum; food and necessities kept before repayments.')
    if data["other"]:
        amount("Other monthly income", data["other"])
    if data["lump"]:
        amount("One-off lump sum", data["lump"])
    if base.get('repayment_priority'):
        text('Bills, food/necessities -> Amex -> repayments -> reserve top-ups -> extra savings/investments.')
        if base.get('amex', {}).get('balance') is None:
            text('Amex balance unknown: confirm it before extra savings or top-ups.')
    if forecast["run_out"]:
        text(
            "FUNDING WARNING: this pathway breaches protected reserves. Review costs before making transfers."
        )

    from finance.bank_balance_receipt import bank_balances

    bank_balances(page, base)

    section("WHAT TO MOVE THIS PAYDAY")
    text(f"{data['start']:%d %b} to {result['cycle_end']:%d %b %Y}")
    destinations = [(name(row), row["first"]) for row in accounts if row["first"]]
    moved = sum((value for _, value in destinations), ZERO)
    if first["savings"] - moved:
        destinations.append(("Savings - choose an account", first["savings"] - moved))
    investment_destinations = list(destinations)
    if first["extra"]:
        debt = ("Amex - extra repayment", first["extra"])
        destinations.insert(0, debt) if data[
            "strategy"
        ] == "amex_first" else destinations.append(debt)
    early_destinations = [(item['name'] + ' - settle early', item['amount']) for item in first.get('instalment_payoffs', [])]
    index = 1 if first['extra'] and data['strategy'] == 'amex_first' else 0
    destinations[index:index] = early_destinations
    from finance.reserve_targets_receipt import transfers as target_transfers
    if base.get('repayment_priority'):
        if first['extra']:
            amount('Amex - extra repayment', first['extra'])
        for label, value in early_destinations:
            amount(label, value)
        target_transfers(page, base, first)
        for label, value in investment_destinations:
            amount(label, value)
    else:
        for label, value in destinations:
            amount(label, value)
    if (
        not destinations
        and not reserve.get("gap")
        and not max(
            ZERO, data.get("monzo_target", ZERO) - base.get("monzo_balance", ZERO)
        )
    ):
        text("No extra transfers available this payday." if base.get("repayment_priority") else "No transfers needed this payday.")
    if not base.get("repayment_priority"):
        reserved_topups = False
        if reserve.get("gap"):
            funded = not base.get("cash_topup") or any(
                e["date"] <= first["end"] for e in forecast["reserve_transfers"]
            )
            amount(
                "Cash top-up (from reserves)" if funded else "Cash top-up - funding needed",
                reserve["gap"],
            )
            reserved_topups = funded
            if not funded:
                text("Not credited to the cash goal this period.")
        monzo_gap = max(
            ZERO, data.get("monzo_target", ZERO) - base.get("monzo_balance", ZERO)
        )
        if monzo_gap:
            amount(
                "Monzo top-up (from reserves)"
                if first["opening"] >= base["buffer"]
                else "Monzo top-up - funding needed",
                monzo_gap,
            )
            reserved_topups = reserved_topups or first["opening"] >= base["buffer"]
        if reserved_topups:
            text("Top-ups use reserves, not extra income.")
    spare = first["cash_repaid"] + first["cash_invested"] + first.get("instalment_cash", ZERO)
    if spare:
        amount("Spare cash (included above)", spare)
    regular = [
        bill
        for bill in result["bills"]
        if bill.get("savings_account")
        or bill.get("category") == "savings"
        or "hargreaves" in bill["name"].casefold()
        or bill["name"].casefold().strip() == "hlam regular saving"
    ]
    if regular:
        amount(
            "Scheduled savings - do not resend",
            sum((bill["amount"] for bill in regular), ZERO),
        )
        if any(not bill.get("savings_account") for bill in regular):
            text(
                "Some regular savings are unlinked; check destinations on the website."
            )
    if forecast.get("capped_savings_events"):
        text(
            "Scheduled savings are capped in this plan; adjust standing orders to match."
        )

    from finance.early_payoff_receipt import overview
    overview(page, forecast, data)

    section("WHAT TO KEEP")
    amount("Bills / regular payments", first["costs"])
    amount("Everyday spending incl. necessities", result["variable"])
    from finance.reserve_targets_receipt import keep as target_keep
    if not target_keep(page, base, first):
        bank_reserve = (
            base["buffer"]
            - money(reserve.get("gap"), ZERO)
            - money(reserve.get("tax_reserve"), ZERO)
        )
        amount(
            "HSBC reserve" if base.get("primary_bank") == "HSBC" else "Main bank reserve",
            max(ZERO, bank_reserve - data.get("monzo_target", ZERO)),
        )
        if data.get("monzo_target"):
            amount("Monzo reserve target", data["monzo_target"])
        if reserve.get("tax_reserve"):
            amount(reserve.get("reserve_label", "Tax reserve"), reserve["tax_reserve"])
    if first.get("retained_in_bank"):
        amount("No savings room - stays in bank", first["retained_in_bank"])

    from finance.monthly_balances import render as month_end_balances
    month_end_balances(page, forecast)
    section("BALANCES AT FORECAST END")
    text(f"On {forecast['end']:%d %b %Y}")
    if forecast.get('reserve_targets_pending'):
        amount('Still needed for HSBC / Monzo / Cash targets', forecast['reserve_targets_pending'])
    from finance.repayment_priority import bank_balances as projected_bank_balances
    hsbc_end, monzo_end = projected_bank_balances(base, forecast, data.get('monzo_target', Decimal(0)))
    amount(base.get('primary_bank', 'Bank cash'), hsbc_end)
    if data.get("monzo_target"):
        amount("Monzo", monzo_end)
    if forecast["card_end"] is None:
        text("Amex balance owed: unavailable")
    else:
        amount("Amex - balance owed", forecast["card_end"])
    from finance.savings_interest import render_account_interest
    for row in accounts:
        amount(name(row), row["projected"]) if row["projected"] is not None else text(
            name(row) + ": balance unavailable"
        )
        render_account_interest(page, row)
    amount("Projected savings total", forecast["savings_end"])
    if forecast.get("savings_interest"):
        amount("Estimated savings interest", forecast["savings_interest"])
        text("Included in savings balances; not a transfer.")

    section("PROGRESS TOWARDS GOALS")
    card = base.get("amex") or {}
    if card.get("balance"):
        amount("Amex owed now", card["balance"])
        if forecast["payoff"]:
            text(f"Amex cleared: around {forecast['payoff']:%B %Y}")
        elif forecast["card_end"]:
            text("Amex not cleared in selected forecast.")
    for row in accounts:
        text(name(row).upper())
        if row["balance"] is None:
            text("Record a current balance to estimate progress.")
            continue
        amount("Current balance", row["balance"])
        if row["target"]:
            amount("Target balance", row["target"])
            current = min(Decimal(100), row["balance"] / row["target"] * 100)
            future = min(Decimal(100), row["projected"] / row["target"] * 100)
            text(f"Progress: {current:.0f}% now -> {future:.0f}% at end")
        amount("Planned contributions", row["added"])
        if row.get("estimated_interest"):
            amount("Estimated interest (before tax)", row["estimated_interest"])
            text(f"Interest assumption: {row['interest_rate']:.2f}% AER")
        if row["target"]:
            reached = row["goal_date"] or row.get("extended_goal_date")
            if reached == "already":
                text("Target already reached.")
            elif reached:
                target_date(reached, not row["goal_date"])
            elif row.get("estimated_goal_date"):
                text("Not reached within selected forecast.")
                target_date(row["estimated_goal_date"], label="Long-term estimate:")
                text("Uses final-year contribution pace and recorded interest; not a funded forecast.")
            else:
                text(
                    f"Target not reached within the {forecast.get('extended_goal_months', data['months'])}-month planning period."
                    if data["mode"] != "lump"
                    else "Target not reached with this one-off lump sum."
                )
        text("")
    if data["goal"]:
        text("OVERALL SAVINGS GOAL")
        amount("Target savings balance", data["goal"])
        reached = forecast["goal_date"] or forecast.get("extended_goal_date")
        if data["starting_savings"] >= data["goal"]:
            text("Goal already met at the starting balance.")
        elif forecast["goal_date"]:
            target_date(reached, label="Projected goal date:")
        else:
            text(f"Goal not reached within the {data['months']}-month forecast.")
            amount(
                "Still to save at forecast end",
                max(ZERO, data["goal"] - forecast["savings_end"]),
            )
            if reached:
                target_date(reached, True, "Extended projected goal date:")
    if not accounts and not data["goal"] and not card.get("balance"):
        text("No account goal or debt balance selected.")

    section("WILL THIS COVER YOUR SPENDING?")
    if forecast["run_out"]:
        text(f"Reserves breached: {forecast['run_out']:%d %b %Y}")
    else:
        text(f"Bills / necessities funded through {forecast['end']:%d %b %Y}." if base.get("repayment_priority") else f"Reserves stay protected through {forecast['end']:%d %b %Y}.")
    if data.get("minimum_bank_balance"):
        amount("Minimum bank balance to keep", data["minimum_bank_balance"])
    amount("Lowest projected bank balance", forecast["minimum_bank"])
    if forecast["end_cash"] < ZERO and not forecast.get('priority_reserves'):
        amount("Funding shortfall at forecast end", -forecast["end_cash"])

    section("PLAN NOTES")
    if data["use_accounts"]:
        text(
            "Savings split: equal between eligible accounts."
            if data["equal_savings"]
            else "Savings split: saved contribution shares."
        )
    if data.get("respect_isa_allowance"):
        text("ISA tax-year contribution limits enabled; uses recorded subscriptions.")
    if data["invest_spare_cash"]:
        text(
            "Extra investments from spare bank cash require salary. Amex repayment can use available cash after necessities." if base.get("repayment_priority") else "Spare bank cash follows the strategy only after salary. No salary: spare-cash investment paused."
        )
    if card.get("balance") and forecast["apr"] is None:
        text("Amex APR unknown: interest excluded.")
    if forecast.get("savings_interest"):
        text(
            "Savings interest assumes constant AER, retained interest and a 365-day year; excludes tax, fees and provider credit dates."
        )
    if not result["account_plan"]["complete"] and data["use_accounts"]:
        text("Savings totals include known balances only.")
    for warning in dict.fromkeys(base.get("warnings", [])):
        text(warning)
    text("Approximate dates. Full workings are on the website or detailed receipt.")
    page.rule()
    text("SIMULATION ONLY - LIVE RECORDS UNCHANGED")
    return page.render()
