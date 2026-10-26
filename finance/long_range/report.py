"""Planning comparisons, auditable balance equations and concise receipt summaries."""

from datetime import date
from decimal import Decimal
from finance.long_range.engine import run
from finance.money import format_pounds as pounds, rounded
from finance.receipt_text import ReceiptText
from finance.visuals import line_chart


def compare(config, observations=()):
    cases = [
        run(config, key, details=key == "expected")
        for key in ("low", "expected", "high")
    ]
    expected = cases[1]
    missed = run(config, missed_salary=True, details=False)
    late = run(config, late_salary=True, details=False)
    changes = []
    for point in expected["points"]:
        for observed in observations:
            if (
                observed["date"] == point["date"].isoformat()
                and observed["account"] in point["accounts"]
            ):
                planned = point["accounts"][observed["account"]]["closing"]
                actual = Decimal(observed["balance"])
                name = next(
                    a["name"]
                    for a in config["accounts"]
                    if a["id"] == observed["account"]
                )
                changes.append(
                    dict(
                        name=name,
                        date=observed["date"],
                        planned=planned,
                        actual=actual,
                        difference=actual - planned,
                        note=observed["note"],
                    )
                )
    levers = []
    for label, field, change in [
        ("£100/month less everyday spending", "spending", -100),
        ("£100/month extra take-home income", "other_income", 100),
    ]:
        alternative = dict(config)
        alternative[field] = str(max(Decimal(0), Decimal(config[field]) + change))
        model = run(alternative, details=False)
        levers.append(
            dict(
                name=label,
                gain=model["final"]["real_worth"] - expected["final"]["real_worth"],
            )
        )
    levers.sort(key=lambda row: row["gain"], reverse=True)
    milestones = []
    for year in sorted({1, 5, 10, 20, 40, int(config["years"])}):
        if year <= int(config["years"]):
            milestones.append(
                dict(
                    year=year,
                    point=expected["points"][
                        min(
                            len(expected["points"]) - 1,
                            year * 12
                            - 1
                            + (date.fromisoformat(config["start"]).day > 1),
                        )
                    ],
                )
            )
    chart = line_chart(
        "long-range-worth",
        "Net worth in today’s money",
        [
            dict(
                name=label,
                values=[
                    (p["date"], p["real_worth"])
                    for p in result["points"]
                    if p["date"].month == 12 or p is result["points"][-1]
                ],
                color=color,
            )
            for result, label, color in zip(
                cases,
                ("Lower assumptions", "Expected assumptions", "Higher assumptions"),
                ("#9f3448", "#245b87", "#32734a"),
            )
        ],
        "Illustrative assumption cases, not probabilities or guaranteed outcomes. Investment returns include any configured cash yield; fees and flat tax assumptions are deducted.",
    )
    return dict(
        cases=cases,
        expected=expected,
        missed=missed,
        late=late,
        changes=changes,
        chart=chart,
        levers=levers,
        milestones=milestones,
    )


def equation(row):
    return (
        row["opening"]
        + row["transfers_in"]
        - row["transfers_out"]
        + row["interest"]
        + row["growth"]
        + row["prizes"]
        - row["fees"]
        - row["tax"]
    )


def receipt(config, report):
    page = ReceiptText()
    page.section("LONG-TERM PLANNING")
    page.text(config["name"])
    amex=[a for a in config['accounts'] if a['kind']=='debt' and 'amex' in a['name'].casefold()]
    if amex:
        from finance.amex_balance import receipt_status as balance_flag
        balance_flag(page,sum((Decimal(a['balance']) for a in amex),Decimal(0)),label='Starting Amex balance (modelled)')
    page.text(
        f"{config['years']} years from {config['start']}; assumptions reviewed {config['reviewed']}."
    )
    page.text("ILLUSTRATIVE MONTHLY MODEL - NOT A PAYMENT INSTRUCTION")
    for result, label in zip(report["cases"], ("LOWER", "EXPECTED", "HIGHER")):
        page.section(label + " ASSUMPTIONS")
        last = result["final"]
        page.text(f"On {last['date']:%d %b %Y}")
        for name, key in [
            ("Net worth", "net_worth"),
            ("In today's money", "real_worth"),
            ("Accessible assets", "accessible"),
            ("Locked / property assets", "locked"),
            ("Debt owed", "debts"),
            ("Assumed payout cash", "payout_cash"),
        ]:
            page.amount(name, last[key])
    page.section("GOALS - EXPECTED ASSUMPTIONS")
    for goal in report["expected"]["goals"]:
        page.text(goal["name"])
        page.amount("Target at chosen date", goal["target"])
        page.amount("Projected at chosen date", goal["projected"])
        page.text(
            "Estimated goal month: "
            + (
                goal["reached"].strftime("%b %Y")
                if goal["reached"]
                else "outside planning horizon"
            )
        )
        if goal["shortfall"]:
            page.amount("Additional monthly amount (estimate)", goal["extra_monthly"])
    page.section("RESILIENCE")
    for result, label in [
        (report["expected"], "Expected plan"),
        (report["missed"], "First salary missed"),
        (report["late"], "First salary one month late"),
    ]:
        page.text(
            label
            + ": "
            + (
                "minimum breached " + result["first_breach"].strftime("%b %Y")
                if result["first_breach"]
                else "minimum maintained"
            )
        )
    page.text(
        "All monthly account equations, life events and individual returns are on the website. Future prizes and investment gains are assumptions; not available to fund bills implicitly. Prizes are not interest. Inflation, fees and flat tax assumptions are editable; detailed tax rules and market timing are not predicted."
    )
    return page.render()
