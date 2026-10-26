"""Render a compact test receipt; calculation imports remain compatible."""
from receipt.profile import COLUMNS

from decimal import Decimal
from finance.projection import occurs, format_runway, money, day
from finance.test_forecast import is_amex, is_card_payment
from finance.scenario_inputs import validate  # public compatibility export
from finance.scenario_plan import build  # public compatibility export


def receipt(result, today, *, detail="detailed"):
    if detail == "compact":
        from finance.compact_test_receipt import receipt as compact_receipt

        return compact_receipt(result, today)
    if detail != "detailed":
        raise ValueError("Choose compact or detailed finance receipt.")
    from finance.receipt_text import ReceiptText

    page = ReceiptText()
    text, rule, section, amount = page.text, page.rule, page.section, page.amount

    data, base, forecast = result["inputs"], result["projection"], result["forecast"]

    def goal_duration(reached):
        text("Estimated time to target:")
        months = (
            (reached.year - today.year) * 12
            + reached.month
            - today.month
            + (reached.day > today.day)
        )
        text(
            "Now"
            if reached <= today
            else f"About {months} " + ("month" if months == 1 else "months")
        )
        if reached > forecast["end"]:
            text("Beyond selected forecast; same pathway.")

    def goal_progress(
        starting, projected, target, added, *, enabled=True, reserved=Decimal(0)
    ):
        current = min(Decimal(100), starting / target * 100)
        future = min(Decimal(100), projected / target * 100)
        text(f"Goal progress now: {current:.1f}%")
        if not enabled:
            text("Account pathway is disabled.")
            return
        text(f"Projected progress at forecast end: {future:.1f}%")
        if reserved:
            amount(
                "Average ongoing additions / month", (added - reserved) / data["months"]
            )
        else:
            amount("Average saved per forecast month", added / data["months"])
        if starting >= target:
            text("Savings status: target already reached.")
        elif forecast["run_out"]:
            text(
                "Savings status: pathway has a funding shortfall. Review income and costs."
            )
        elif projected >= target:
            text("Savings status: target reached in the selected forecast.")
        elif added > 0:
            text("Savings status: progressing towards target on this pathway.")
        else:
            text("Savings status: no savings added in the selected forecast.")

    first = forecast["payments"][0]
    section("TEST FINANCE")
    text(
        "SIMULATION - LUMP SUM ONLY"
        if data["mode"] == "lump"
        else "SIMULATION - POTENTIAL SALARY"
    )
    text(f"Generated {today:%d %b %Y}")
    text(f"Forecast ends {forecast['end']:%d %b %Y} ({data['months']} months)")
    from finance.bank_balance_receipt import bank_balances

    bank_balances(page, base)

    section("PAY PERIOD ALLOCATION")
    text(f"{data['start']:%d %b} to {result['cycle_end']:%d %b %Y}")
    if data["mode"] in {"lump", "lump_income"}:
        amount("One-off lump sum", data["lump"])
    amount("Monthly salary when active", data["salary"])
    if data["existing"]:
        amount("Existing salary (additional mode)", data["existing"])
    amount("Other monthly income", data["other"])
    amount("INCOME THIS PERIOD", first["salary"] + data["other"])
    text(f"Income receipt date: {data['start']:%d %b %Y}")
    if data["salary_start"] or data["salary_end"] or data["missed_salary_dates"]:
        text(
            "Salary window: "
            + (
                data["salary_start"].isoformat()
                if data["salary_start"]
                else "from first payday"
            )
            + " to "
            + (data["salary_end"].isoformat() if data["salary_end"] else "forecast end")
        )
        amount("Salary received this period", first["salary"])
        if data["missed_salary_dates"]:
            text(f"Skipped salary paydays: {len(data['missed_salary_dates'])}")
    strategies = {
        "savings_first": "Savings first",
        "amex_first": "Amex first",
        "split": f"Split: {data['split'].normalize():f}% to Amex",
    }
    text("Strategy: " + strategies[data["strategy"]])
    if base.get('repayment_priority'):
        text('Bills and food/necessities first; then Amex, repayments, reserve top-ups, then extra savings/investments.')
        if base.get('amex', {}).get('balance') is None:
            text('Amex balance unknown: confirm it before extra savings or top-ups.')
    if first.get('spending_limited'):
        amount('Debt/overdraft spending ceiling', first['spending_cap'])
        text('Monthly maximum; food and necessities kept before repayments.')
    amount("Per day (expected spending)", first.get("daily_spend", base.get("daily_cost", base["daily"])))
    amount(
        "INCOME SURPLUS" if result["surplus"] >= 0 else "INCOME FUNDING GAP",
        abs(result["surplus"]),
    )
    if data["save_all"]:
        text("Saving all remaining income surplus.")
    elif not data["savings"] and not data["invest_spare_cash"]:
        text("Savings target not set")
    if data["invest_spare_cash"]:
        if first["salary"] > 0:
            text(
                "Invest spare bank cash after Amex and reserve targets are funded." if base.get("repayment_priority") else "Use spare bank cash with this strategy; keep at least £1,000 plus bills, spending and other reserves."
            )
        else:
            text("No salary: spare bank cash investment paused.")
    if result["shortfall"]:
        amount("SHORTFALL after reserves", result["shortfall"])
    section("WHERE TO MOVE THIS PAYDAY")
    if data["use_accounts"]:
        text(
            "Savings split: equal between eligible accounts."
            if data["equal_savings"]
            else "Savings split: saved contribution shares."
        )
    if data.get("respect_isa_allowance"):
        text(
            "ISA tax-year contribution limits enabled; based on recorded subscriptions. Transfers and existing balances are separate."
        )
    text("Extra transfers to make:")
    if data["use_accounts"]:
        text(
            "Account limits redirect to other eligible accounts; savings goals do not stop contributions."
        )
    from finance.reserve_targets_receipt import transfers as target_transfers
    if base.get('repayment_priority'):
        if first['extra']:
            amount('Amex - extra repayment', first['extra'])
        for item in first.get('instalment_payoffs', []):
            amount(item['name'] + ' - settle early', item['amount'])
        target_transfers(page, base, first)
    moved = Decimal(0)
    if data["use_accounts"]:
        for account in result["account_plan"]["accounts"]:
            if account["first"]:
                amount(account.get("label", account["name"]), account["first"])
                moved += account["first"]
    unassigned = first["savings"] - moved
    if unassigned:
        amount("Savings - choose an account", unassigned)
    if first.get("retained_in_bank"):
        amount("No eligible savings room - keep in bank", first["retained_in_bank"])
    if not base.get('repayment_priority'):
        if first["extra"]:
            amount("Amex - extra repayment", first["extra"])
        for item in first.get('instalment_payoffs', []):
            amount(item['name'] + ' - settle early', item['amount'])
    if first["cash_repaid"]:
        text(
            f"Includes £{first['cash_repaid']:,.2f} from spare bank cash in the Amex repayment above."
        )
    if first.get('instalment_cash'):
        text(f"Includes £{first['instalment_cash']:,.2f} from spare bank cash in early instalment settlements above.")
    if first["cash_invested"]:
        text(
            f"Includes £{first['cash_invested']:,.2f} from spare bank cash in the savings transfers above."
        )
    reserve = base.get("reserve_details") or {}
    if not base.get("repayment_priority"):
        if reserve.get("gap"):
            if base.get("cash_topup") and not forecast["reserve_transfers"]:
                amount("Cash top-up - funding needed", reserve["gap"])
                text("Not credited to the cash goal yet.")
            else:
                amount("Cash top-up (already reserved)", reserve["gap"])
                if forecast["reserve_transfers"]:
                    text(
                        f"Cash goal credited on {forecast['reserve_transfers'][0]['date']:%d %b %Y} in this plan."
                    )
    if not moved and not unassigned and not first["extra"] and not first.get("instalment_settled") and not reserve.get("gap"):
        text("No extra transfers in this period.")
    regular = [
        bill
        for bill in result["bills"]
        if bill.get("savings_account")
        or bill.get("category") == "savings"
        or "hargreaves" in bill["name"].casefold()
        or bill["name"].casefold().strip() == "hlam regular saving"
    ]
    if forecast.get("capped_savings_events"):
        text(
            "Some scheduled savings are capped in this plan; adjust standing orders to match."
        )
    if regular:
        text("Already scheduled - do not send again:")
        for bill in regular:
            amount(f"{bill['date']:%d %b} {bill['name']}", bill["amount"])
        text("Included in the bills total below.")
        if any(not bill.get("savings_account") for bill in regular):
            text(
                "Unlinked regular payments are not credited to an account goal. Enable saved accounts and check account names."
            )
    amount("Keep for bills / regular payments", first["costs"])
    amount("Everyday spending incl. necessities", result["variable"])
    amount(
        "Income left in bank",
        max(Decimal(0), first["budget"] - first["extra"] - first["savings"] - first.get("instalment_extra", Decimal(0))),
    )
    from finance.reserve_targets_receipt import keep as target_keep
    if not target_keep(page, base, first):
        if reserve.get("gap"):
            text("Cash top-up uses protected reserves; do not deduct it again.")
        if data.get("monzo_target"):
            monzo_gap = max(
                Decimal(0), data["monzo_target"] - base.get("monzo_balance", Decimal(0))
            )
            amount("Monzo target (within bank reserves)", data["monzo_target"])
            if monzo_gap:
                amount(
                    "Move to Monzo from bank reserves"
                    if first["opening"] >= base["buffer"]
                    else "Monzo top-up - funding needed",
                    monzo_gap,
                )
            text("Internal bank transfer; do not deduct it from total bank cash again.")
    contribution = result.get("contribution") or {}
    if contribution.get("available"):
        section("HARGREAVES LANSDOWN PLAN")
        text(contribution["account"])
        for label, key in [
            ("Scheduled this period", "scheduled_this_period"),
            ("Extra from income this period", "income_extra_this_period"),
            ("One-off extra this period", "one_off_this_period"),
            ("Total contribution this period", "total_this_period"),
            ("Suggested regular amount", "suggested"),
            ("Regular amount being compared", "proposed"),
        ]:
            right = contribution[key]
            if len(label) + len(right) + 1 > page.width:
                text(label)
                page.lines.append(right.rjust(page.width))
            else:
                page.lines.append(label + right.rjust(page.width - len(label)))
        for label, key in [
            ("Current pathway target", "goal_keep"),
            ("Compared pathway target", "goal_proposed"),
        ]:
            reached = day(contribution[key])
            text(
                label
                + (
                    ": around " + reached.strftime("%b %Y")
                    if reached
                    else ": no funded date"
                )
            )
            text(contribution["time_keep" if key == "goal_keep" else "time_proposed"])
        text(
            "Comparison includes the scheduled payment; replaces part of the extra allocation. Income-funded increases wait for Amex clearance under Amex first; no increase without salary. See webpage for period amounts. Existing payments continue."
        )
    section("CASH & RESERVES")
    amount("Current bank cash", base["cash"])
    reserve = base.get("reserve_details")
    if reserve:
        amount(
            "Bank / emergency reserve",
            base["buffer"] - reserve["gap"] - reserve["tax_reserve"],
        )
        if reserve["tax_reserve"]:
            amount(reserve.get("reserve_label", "Tax reserve"), reserve["tax_reserve"])
    amount("RESERVE TARGETS" if base.get('repayment_priority') else "TOTAL PROTECTED", base["buffer"])
    if base.get('repayment_priority'):
        text('HSBC/Cash/Monzo targets follow Amex and eligible early repayments. Bills, necessities and other earmarked money remain protected.')
    amount(
        "Existing cash above reserves", max(Decimal(0), base["cash"] - base["buffer"])
    )
    card = base.get("amex")
    if card:
        section("AMEX PLAN")
        if card["balance"] is None:
            text(
                "Balance unavailable. Listed repayments are included; enter Amex owed for payoff modelling."
            )
        else:
            if card.get("full_reserved"):
                amount("Balance owed now", card["balance"])
                text(
                    "Full balance reserved once today; already deducted in the forecast. Additional suggested repayment: £0.00."
                )
            else:
                text("THIS PAY PERIOD")
                text(f"{data['start']:%d %b} to {result['cycle_end']:%d %b %Y}")
                scheduled = sum(
                    (e["amount"] for e in result["bills"] if is_card_payment(e)),
                    Decimal(0),
                )
                interest = max(
                    Decimal(0),
                    first["closing_card"]
                    - first["opening_card"]
                    + scheduled
                    + first["extra"],
                )
                amount("Balance at period start", first["opening_card"])
                if interest >= Decimal("0.005"):
                    amount("Estimated interest this period", interest)
                amount("Scheduled repayment via direct debit this period", scheduled)
                amount("Extra repayment this period", first["extra"])
                amount("Balance at period end", first["closing_card"])
            text("WHOLE FORECAST")
            scheduled_total = sum(
                (e["amount"] for e in forecast["events"] if is_card_payment(e)),
                Decimal(0),
            )
            amount(
                "Scheduled repayments via direct debit over forecast", scheduled_total
            )
            amount("Extra repayments over forecast", forecast["extra_total"])
            amount("Amex owed at forecast end", forecast["card_end"])
            if forecast["payoff"]:
                text(f"Projected Amex cleared: around {forecast['payoff']:%B %Y}")
            else:
                text(
                    "Amex not cleared within this forecast."
                    if forecast["card_end"]
                    else "No outstanding Amex balance."
                )
            if forecast["apr"] is None:
                text(
                    "Rate unknown: interest excluded. Enter APR to include estimated interest."
                )
            else:
                text(f"APR assumption: {forecast['apr']}%")
                amount("Estimated interest over forecast", forecast["interest"])

    from finance.early_payoff import options as payoff_options
    selected = {row['id'] for row in forecast.get('instalment_balances', [])}
    selected_records = [row['record'] for row in payoff_options(base.get('repayment_options', [])) if row['id'] in selected]
    options = [
        item
        for item in base.get("repayment_options", [])
        if not is_amex(item.get("name")) and item not in selected_records
    ]
    if options:
        section("OTHER REPAYMENTS")
    budget = max(Decimal(0), first["budget"] - first["extra"] - first["savings"] - first.get("instalment_extra", Decimal(0)))
    for item in options:
        text(str(item.get("name") or "Repayment").upper())
        balance = money(item.get("remaining_balance", item.get("balance")))
        payment = money(item.get("monthly_payment", item.get("amount")))
        final = day(item.get("end_date"))
        rate = money(item.get("apr", item.get("interest_rate")))
        if balance is not None:
            amount("Remaining balance", balance)
        if payment:
            amount("Monthly cost freed on completion", payment)
        if final:
            text(f"Final payment: {final:%d %b %Y}")
        if item.get("payments_remaining") is not None:
            text(f"Payments remaining: {item['payments_remaining']}")
        if balance is None or rate is None:
            text("Confirm balance/rate and early repayment terms before deciding.")
        elif balance > 0 and budget >= balance:
            amount("Potential full payoff", balance)

    if result["account_plan"]["accounts"]:
        section("RECORDED SAVINGS & INVESTMENTS")
        for index, account in enumerate(result["account_plan"]["accounts"]):
            if index:
                rule()
            text(account.get("label", account["name"]).upper())
            from finance.savings_targets import contribution_limit

            limit = contribution_limit(account)
            if limit is not None:
                amount("Maximum balance", limit)
            elif account["target"]:
                text("Goal is a milestone; contributions continue.")
            if account["balance"] is None:
                text(
                    "Balance unavailable; excluded from totals and contribution allocation."
                )
                if account["target"]:
                    amount("Target balance", account["target"])
                text("Time to target unavailable until balance is recorded.")
                continue
            amount("Current balance", account["balance"])
            if account.get("date"):
                text(f"Recorded {account['date']}")
            else:
                text("Balance date not recorded.")
            if account["target"]:
                amount("Target balance", account["target"])
            amount("Planned contributions", account["added"])
            if (
                account.get("interest_rate") is not None
                and account["type"] in {"savings", "cash_isa"}
                and not account.get("cash_reserve_limit")
            ):
                text(f"Interest assumption: {account['interest_rate']:.2f}% AER")
                if account.get("rate_date"):
                    text(f"Rate effective from {account['rate_date']}")
                amount("Estimated interest (before tax)", account["estimated_interest"])
            amount("Projected account balance", account["projected"])
            if account["target"]:
                if account["projected"] < account["target"]:
                    amount(
                        "Still to save at forecast end",
                        account["target"] - account["projected"],
                    )
                goal_progress(
                    account["balance"],
                    account["projected"],
                    account["target"],
                    account["added"],
                    enabled=data["use_accounts"],
                    reserved=account["reserved_added"],
                )
                reached = account["goal_date"] or account.get("extended_goal_date")
                if reached == "already":
                    text("Target already reached.")
                elif reached:
                    if not account["goal_date"]:
                        text("Not reached within selected forecast.")
                    text(
                        f"Projected target date: around {reached:%B %Y}"
                        + (" (extended)" if not account["goal_date"] else "")
                    )
                    goal_duration(reached)
                elif account.get("estimated_goal_date"):
                    text("Not reached within selected forecast.")
                    text(f"Long-term estimate: around {account['estimated_goal_date']:%B %Y}")
                    goal_duration(account["estimated_goal_date"])
                    text("Uses final-year contribution pace and recorded interest; not a funded forecast.")
                elif not data["use_accounts"]:
                    text("Enable saved account allocation to estimate time to target.")
                else:
                    text("No funded target date in this plan.")
                    text(
                        f"Target not reached within the {forecast.get('extended_goal_months', data['months'])}-month planning period."
                        if data["mode"] != "lump"
                        else "Target not reached with this one-off lump sum."
                    )
            else:
                text("No account balance target set.")
            if account["isa_contributions"] is not None:
                amount(
                    "Recorded ISA contributions this FY", account["isa_contributions"]
                )
                text("ISA allowance progress is separate from the balance target.")
        if forecast["unallocated_savings"]:
            amount(
                "New savings not assigned to accounts", forecast["unallocated_savings"]
            )
        if not data["use_accounts"]:
            text(
                "Account allocation disabled; overall goal uses the manual starting savings input."
            )
        if not result["account_plan"]["complete"]:
            text("Totals include known balances only.")

    section("SAVINGS PROJECTION")
    amount("Starting savings (separate to cash)", data["starting_savings"])
    amount(
        "Extra savings transfers over forecast",
        forecast["savings_total"] - forecast["cash_invested_total"],
    )
    if data["invest_spare_cash"]:
        amount(
            "Spare bank cash invested over forecast", forecast["cash_invested_total"]
        )
    if forecast["automatic_total"]:
        amount("Scheduled savings over forecast", forecast["automatic_total"])
    if forecast["reserved_total"]:
        amount("Cash top-ups actually funded" if base.get("repayment_priority") else "One-off cash top-up from reserves", forecast["reserved_total"])
    if forecast.get("savings_interest"):
        amount("Estimated savings interest", forecast["savings_interest"])
    from finance.early_payoff_receipt import overview
    overview(page, forecast, data, detailed=True)
    from finance.monthly_balances import render as month_end_balances
    month_end_balances(page, forecast)
    section("BALANCES AT FORECAST END")
    if forecast.get('reserve_targets_pending'):
        amount('Still needed for HSBC / Monzo / Cash targets', forecast['reserve_targets_pending'])
    from finance.repayment_priority import bank_balances as projected_bank_balances
    hsbc_end, monzo_end = projected_bank_balances(base, forecast, data.get('monzo_target', Decimal(0)))
    amount(base.get('primary_bank', 'Bank cash'), hsbc_end)
    if data.get("monzo_target"):
        amount("Monzo", monzo_end)
        if monzo_end < data["monzo_target"]:
            text("Monzo target is not funded at forecast end.")
    if forecast["card_end"] is None:
        text("Amex balance owed: unavailable")
    else:
        amount("Amex - balance owed", forecast["card_end"])
    if data["use_accounts"]:
        from finance.savings_interest import render_account_interest
        for account in result["account_plan"]["accounts"]:
            if account["projected"] is not None:
                amount(account.get("label", account["name"]), account["projected"])
            else:
                text(account.get("label", account["name"]) + ": balance unavailable")
            render_account_interest(page, account)
    text("Projected balances only; no money is moved.")
    amount("Projected savings at forecast end", forecast["savings_end"])
    if not forecast["savings_total"]:
        text(
            "No extra savings transfers assumed in this test."
            if forecast["automatic_total"] or forecast["reserved_total"]
            else "No savings transfers assumed in this test."
        )
    else:
        text("Bank cash excludes transferred savings.")
    if data["goal"]:
        section("SAVINGS GOAL")
        amount("Target savings balance", data["goal"])
        amount(
            "Still to save at start",
            max(Decimal(0), data["goal"] - data["starting_savings"]),
        )
        goal_progress(
            data["starting_savings"],
            forecast["savings_end"],
            data["goal"],
            forecast["savings_total"]
            + forecast["automatic_total"]
            + forecast["reserved_total"],
            reserved=forecast["reserved_total"],
        )
        if data["starting_savings"] >= data["goal"]:
            text("Goal already met at the starting balance.")
        elif forecast["goal_date"]:
            text(f"Projected goal date: around {forecast['goal_date']:%B %Y}")
            goal_duration(forecast["goal_date"])
        else:
            text(f"Goal not reached within the {data['months']}-month forecast.")
            amount(
                "Still to save at forecast end",
                max(Decimal(0), data["goal"] - forecast["savings_end"]),
            )
            if forecast.get("extended_goal_date"):
                text(
                    f"Extended projected goal date: around {forecast['extended_goal_date']:%B %Y}"
                )
                goal_duration(forecast["extended_goal_date"])
            elif (
                not forecast["savings_total"]
                and not forecast["automatic_total"]
                and not forecast["reserved_total"]
            ):
                text(
                    "No savings contribution selected or available; no funded goal date within the planning period."
                )
            else:
                text(
                    f"No funded goal date within the {forecast.get('extended_goal_months', data['months'])}-month planning period."
                )
    section("RUNWAY WITH TEST INCOME")
    if forecast["run_out"]:
        text(f"Reserves breached: {forecast['run_out']:%d %b %Y}")
        text(format_runway((forecast["run_out"] - today).days, today))
    else:
        text(f"No shortfall through {forecast['end']:%d %b %Y}")
    reserve = base.get("reserve_details") or {}
    amount(
        "Bank reserve target" if base.get("repayment_priority") else "Bank reserve kept",
        base["buffer"]
        - money(reserve.get("gap"), Decimal(0))
        - money(reserve.get("tax_reserve"), Decimal(0)),
    )
    amount("Bank cash above reserves at end", max(Decimal(0), forecast["end_cash"]))
    if forecast["end_cash"] < 0:
        amount("Still needed for HSBC / Monzo / Cash targets" if base.get('repayment_priority') else "Funding shortfall at forecast end", -forecast["end_cash"])
    if data.get("minimum_bank_balance"):
        amount("Minimum bank balance to keep", data["minimum_bank_balance"])
    amount("Lowest projected bank balance", forecast["minimum_bank"])
    text(
        "Bills and necessities funded; reserve goals follow Amex and eligible early repayments." if base.get("repayment_priority") else "Protected reserves hold through forecast."
        if not forecast["run_out"]
        else "Protected reserves would be breached."
    )
    reached = sum(
        1
        for row in result["account_plan"]["accounts"]
        if row["target"] and row["goal_date"]
    )
    if data["use_accounts"]:
        text(
            f"Account goals reached: {reached} of "
            + str(sum(1 for row in result["account_plan"]["accounts"] if row["target"]))
        )
    if result.get("sensitivity"):
        text(result["sensitivity"]["message"])
        if result["sensitivity"].get("goal_message"):
            text(result["sensitivity"]["goal_message"])
    section("ASSUMPTIONS")
    text("Rough planning estimate; goal dates are approximate.")
    text(
        f"Forecast: {data['months']} months from {data['start']:%d %b %Y}. Goal durations measured from {today:%d %b %Y}."
    )
    if data["invest_spare_cash"]:
        text(
            "Bills and food/necessities first, then Amex, eligible early repayments, then HSBC/Cash/Monzo targets. Extra investments from spare bank cash require salary and funded reserve targets." if base.get("repayment_priority") else "Spare bank cash follows the selected strategy on salary paydays; Amex first repays Amex before extra savings. Protects £1,000, bills, everyday spending and other reserves. No salary means no spare cash investment. Uses selected account shares and targets."
        )
    else:
        text(
            "Extra savings use recurring income surplus after bills, spending and reserves; existing bank cash is not used for extra savings."
        )
    text("Existing scheduled savings continue as commitments. Cash top-ups are shown separately.")
    text(
        "Salary follows selected dates; other income continues. One-off costs occur once; finite repayments stop at completion. "
        + (
            "No new card purchases assumed. "
            if forecast.get("savings_interest")
            else "No savings growth or new card purchases assumed. "
        )
        + "Goal dates are estimates; no transfers are made."
    )
    if forecast.get("savings_interest"):
        text(
            "Savings growth estimates retain interest at the entered AER using a 365-day year. Rates stay constant from their effective date; excludes tax, fees and provider credit dates. Interest is not a bank transfer or ISA subscription. Investment growth is excluded."
        )
    for warning in base.get("warnings", []):
        text(warning)
    rule()
    text("SIMULATION ONLY - LIVE RECORDS UNCHANGED")
    rule()
    return page.render()
