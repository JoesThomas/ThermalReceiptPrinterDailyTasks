"""Small chart view models from existing forecasts; no provider requests or new assets."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from finance.money import parse, format_pounds
from finance.projection import day

ZERO = Decimal(0)
COLORS = [
    "#176b59",
    "#365eb0",
    "#b94e18",
    "#873ea0",
    "#976800",
    "#137b8d",
    "#b33062",
    "#485b69",
]


def line_chart(key, title, series, note="", markers=None, band=None):
    series = [s for s in series if s.get("values")]
    values = [v for s in series for _, v in s["values"] if v is not None]
    dates = [on for s in series for on, v in s["values"] if v is not None]
    if not values or not dates:
        return None
    start, end = min(dates), max(dates)
    low, high = min([ZERO] + values), max([Decimal(1)] + values)
    if band is not None:
        low, high = min(low, ZERO, band), max(high, band)
    raw_step=max(Decimal('0.01'),(high-low)/5)
    magnitude=Decimal(10)**raw_step.adjusted()
    step=next(magnitude*n for n in (Decimal(1),Decimal(2),Decimal('2.5'),Decimal(5),Decimal(10)) if magnitude*n>=raw_step)
    low=(low/step).to_integral_value(rounding=ROUND_FLOOR)*step
    high=(high/step).to_integral_value(rounding=ROUND_CEILING)*step
    if high==low:high=low+step
    span = max(Decimal(1), high - low)

    def x(on):
        return round(58 + 620 * (on - start).days / max(1, (end - start).days), 2)

    def y(value):
        return round(float(220 - (value - low) / span * 185), 2)

    rows = []
    for index, s in enumerate(series):
        data = [(on, parse(value)) for on, value in s["values"] if value is not None]
        rows.append(
            dict(
                name=s["name"],
                color=COLORS[index % len(COLORS)],
                dash="6 4" if s.get("reference") else "",
                reference=bool(s.get("reference")),
                points=" ".join(f"{x(on)},{y(value)}" for on, value in data),
                data=[
                    dict(date=on.isoformat(), value=format_pounds(value), raw=str(value))
                    for on, value in data
                ],
            )
        )
    return dict(
        key=key,
        title=title,
        note=note,
        series=rows,
        start=start.isoformat(),
        end=end.isoformat(),
        high=format_pounds(high),
        axis_low=str(low),axis_high=str(high),band_value=str(band) if band is not None else None,
        y_ticks=[dict(y=y(low+step*i),label=format_pounds(low+step*i).replace('.00','')) for i in range(int((high-low)/step)+1)],
        x_ticks=[dict(x=x(start+(end-start)*i/4),label=(start+(end-start)*i/4).strftime('%b %Y')) for i in range(5)],
        low=format_pounds(low),
        zero=y(ZERO),
        band_y=y(band) if band is not None else None,
        markers=[
            dict(x=x(on), label=label, date=on.isoformat())
            for on, label in (markers or [])
            if start <= on <= end
        ][:20],
    )


def main_cash(projection, expected_rows, today, days=30):
    if not projection or not projection["valid"]:
        return None
    from finance.expected_income import scheduled, compare

    count = min(days, projection["horizon"])
    scoped = dict(
        projection, horizon=count, horizon_end_date=today + timedelta(days=count)
    )
    events = scheduled(expected_rows, today, scoped["horizon_end_date"])
    baseline = compare(scoped, [], today)
    expected = compare(scoped, events, today)
    buffer = projection["buffer"]
    series = [
        dict(
            name="No future income",
            values=[(day(p["date"]), p["cash"] + buffer) for p in baseline["timeline"]],
        )
    ]
    if events:
        series.append(
            dict(
                name="Expected non-salary income",
                values=[
                    (day(p["date"]), p["cash"] + buffer) for p in expected["timeline"]
                ],
            )
        )
    # compare normally retains only 30 days; a longer view is sampled separately.
    if count > 30:
        costs = {}
        incomes = {}
        for e in projection["events"]:
            costs[e["date"]] = costs.get(e["date"], ZERO) + e["amount"]
        for e in events:
            incomes[e["date"]] = incomes.get(e["date"], ZERO) + e["amount"]
        a = b = projection["cash"]
        left = []
        right = []
        for offset in range(count + 1):
            on = today + timedelta(days=offset)
            a -= costs.get(on, ZERO) + (
                projection.get("daily_cost", projection["daily"]) if offset else ZERO
            )
            b -= costs.get(on, ZERO) + (
                projection.get("daily_cost", projection["daily"]) if offset else ZERO
            )
            b += incomes.get(on, ZERO)
            left.append((on, a))
            right.append((on, b))
        series[0]["values"] = left
        if events:
            series[1]["values"] = right
    series.append(
        dict(
            name="Protected cash buffer",
            values=[(today, buffer), (scoped["horizon_end_date"], buffer)],
            reference=True,
        )
    )
    markers = [(e["date"], e["name"]) for e in events]
    markers += [
        (e["date"], e["name"])
        for e in projection["events"]
        if today < e["date"] <= scoped["horizon_end_date"] and e["amount"] >= 100
    ]
    return line_chart(
        f"main-cash-{days}",
        f"Bank cash · next {days} days",
        series,
        "Forecast, not bank history. Shading marks protected reserves. Expected income excludes salary. Markers show incoming payments and bills of £100 or more.",
        markers,
        buffer,
    )


def bank_path(result):
    f, b = result["forecast"], result["projection"]
    return [
        (
            p["date"],
            p["scenario"]
            + b["buffer"]
            - sum(
                (e["amount"] for e in f["reserve_transfers"] if e["date"] <= p["date"]),
                ZERO,
            ),
        )
        for p in f["points"]
    ]


def savings_chart(result, today):
    from finance.savings_interest import Growth

    accounts = (
        result["account_plan"]["accounts"] if result["inputs"]["use_accounts"] else []
    )
    known = [deepcopy(row) for row in accounts if row["balance"] is not None]
    if not known:
        return None
    for row in known:
        row["projected"] = row["balance"]
        row["goal_date"] = None
    growth = Growth(known, today)
    by_id = {r["id"]: r for r in known}
    events = []
    for row in known:
        events.extend((e["date"], row["id"], e["total"]) for e in row["allocations"])
    events.extend(
        (e["date"], e["savings_account"], e["amount"])
        for e in result["forecast"]["events"] + result["forecast"]["reserve_transfers"]
        if e.get("savings_account") in by_id
    )
    by_date = {}
    for on, key, amount in events:
        by_date.setdefault(on, []).append((key, amount))
    end = result["forecast"]["end"]
    dates = sorted(set([today, end, *by_date]))
    paths = {r["id"]: [(today, r["balance"])] for r in known}
    for on in dates:
        if not today <= on <= end:
            continue
        growth.advance(on)
        for key, amount in by_date.get(on, []):
            by_id[key]["projected"] += amount
        for row in known:
            paths[row["id"]].append((on, row["projected"]))
    series = []
    for row in known:
        # Endpoint is the authoritative account projection, including its rounded interest.
        paths[row["id"]][-1] = (
            end,
            row["projected"]
            if row["projected"] is None
            else next(a["projected"] for a in accounts if a["id"] == row["id"]),
        )
        name = row.get("label", row["name"])
        series.append(dict(name=name, values=paths[row["id"]]))
        for field, label in [("target", "goal"), ("balance_limit", "contribution cap")]:
            value = parse(row.get(field))
            if field == "balance_limit":
                from finance.savings_targets import contribution_limit

                value = contribution_limit(row)
            if value:
                series.append(
                    dict(
                        name=f"{name} · {label}",
                        values=[(today, value), (end, value)],
                        reference=True,
                    )
                )
    return line_chart(
        "test-savings",
        "Savings balances and goals",
        series,
        "Calculated from the same dated allocations and AER assumptions as the receipt. Goals are milestones; caps stop new contributions. Interest may take a balance above a cap. Hide series to focus on an account.",
    )


def debt_chart(result, today):
    from finance.test_forecast import is_card_payment

    f, b = result["forecast"], result["projection"]
    balance = b.get("amex", {}).get("balance")
    if balance is None or balance <= ZERO:
        return None
    rate = (f["apr"] or ZERO) / 100 / 365
    scheduled = {}
    for e in b["events"]:
        if is_card_payment(e):
            scheduled[e["date"]] = scheduled.get(e["date"], ZERO) + e["amount"]
    chosen = [(today, balance)] + [
        (p["end"], p.get("closing_card", p["balance_after_extra"]))
        for p in f["payments"]
    ]
    baseline = []
    debt = balance
    for offset in range((f["end"] - today).days + 1):
        on = today + timedelta(days=offset)
        if offset:
            debt += debt * rate
        debt = max(ZERO, debt - scheduled.get(on, ZERO))
        if offset % 7 == 0 or on == f["end"]:
            baseline.append((on, debt))
    chosen[-1] = (f["end"], f["card_end"])
    return line_chart(
        "test-amex",
        "Amex repayment comparison",
        [
            dict(name="Selected repayment plan", values=chosen),
            dict(name="Scheduled payments only", values=baseline),
        ],
        "Same opening debt and APR assumption. The comparison removes extra repayments; it does not change your direct debit. Unknown APR means interest is excluded.",
    )


def allocation(result):
    p = result["forecast"]["payments"][0]
    b = result["projection"]
    reserve = b.get("reserve_details") or {}
    rows = [
        ("Scheduled bills and payments", p["costs"]),
        ("Everyday spending", p["variable"]),
        ("Extra Amex repayment", p["extra"]),
        ("Extra savings transfers", p["income_savings"] + p["cash_invested"]),
        (
            "Retained bank cash",
            max(
                ZERO,
                p["cash_after_allocation"] + b["buffer"] - (p.get("cash_topups_total", ZERO) if b.get("repayment_priority") else reserve.get("gap", ZERO)),
            ),
        ),
    ]
    if p.get("instalment_settled"):
        rows.insert(3, ("Early instalment settlements", p["instalment_settled"]))
    if p.get('reserve_targets', {}).get('cash_transfer'):
        rows.insert(3, ('Physical cash top-up', p['reserve_targets']['cash_transfer']))
    total = sum((max(ZERO, v) for _, v in rows), ZERO)
    return dict(
        rows=[
            dict(
                label=k,
                value=format_pounds(v),
                percent=float(max(ZERO, v) / total * 100) if total else 0,
                color=COLORS[i],
            )
            for i, (k, v) in enumerate(rows)
        ],
        note="Planned cash uses, including spare starting bank cash where selected. Scheduled savings and direct debits are included once in scheduled payments. Cash/Monzo top-ups are internal or reserved transfers, not additional income. A shortfall means some planned uses are unfunded.",
    )


def test_charts(result, today, cases):
    b = result["projection"]
    f = result["forecast"]
    policy = b.get("repayment_priority")
    floor = policy["hard"] if policy else b["buffer"] - f["reserved_total"]
    charts = [
        line_chart(
            "test-bank",
            "Bank cash and protected reserves",
            [
                dict(name="Selected forecast", values=bank_path(result)),
                dict(
                    name="Minimum bank balance and other protected reserves" if policy else "Protected buffer after reserved top-ups",
                    values=[(today, floor), (f["end"], floor)],
                    reference=True,
                ),
            ],
            "Selected forecast period. Below the buffer means a funding shortfall; forecasts after that point are hypothetical.",
            band=floor,
        ),
        savings_chart(result, today),
        debt_chart(result, today),
        line_chart(
            "test-cases",
            "What if? · bank cash comparison",
            [dict(name=name, values=bank_path(case)) for name, case in cases],
            "Illustrative changes to the same starting balances and strategy; these are not probability ranges. Exact dates and assumptions are below.",
        ),
    ]
    cash_chart=charts[0]
    if cash_chart:
        cash_chart['stats']=[dict(label='Lowest daily bank balance',value=format_pounds(f['minimum_bank']),note=f['minimum_date'].strftime('%d %b %Y'),warning=f['minimum_bank']<floor),
                             dict(label='Protected minimum',value=format_pounds(floor),note='Includes other protected earmarks'),
                             dict(label='Bank balance at forecast end',value=format_pounds(f['end_cash']+b['buffer']-f['reserved_total']),note=f['end'].strftime('%d %b %Y'))]
        ranges=f.get('monthly_ranges',[])
        if ranges:
            monthly=line_chart('test-bank','Bank cash and protected reserves',[
                dict(name='Monthly lowest balance',values=[(r['date'],r['low']) for r in ranges]),
                dict(name='Monthly highest balance',values=[(r['date'],r['high']) for r in ranges]),
                dict(name='Protected minimum',values=[(today,floor),(f['end'],floor)],reference=True)],
                'Monthly lows/highs use every modelled day. The shaded range shows how cash varies between paydays and bills; it is not an uncertainty interval. Switch to cash-flow samples to inspect the rises and falls.',band=floor)
            monthly['range_band']=True
            monthly['stats']=cash_chart['stats']
            if data_months := result['inputs'].get('months'):
                if data_months>6:
                    monthly['alt_model']=cash_chart;monthly['mode']='monthly';charts[0]=monthly
                else:
                    cash_chart['alt_model']=monthly;cash_chart['mode']='cashflow'
    return dict(lines=[c for c in charts if c], allocation=allocation(result))
