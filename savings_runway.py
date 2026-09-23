from __future__ import annotations
from pathlib import Path
import json

def load_savings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": []}
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    return {"accounts": accounts if isinstance(accounts, list) else []}

def savings_totals(data: dict) -> dict:
    total = 0.0
    net_cash = 0.0
    runway = 0.0
    accounts = []
    for raw in data.get("accounts", []):
        try:
            balance = float(raw.get("balance", 0))
        except Exception:
            balance = 0.0
        row = {
            "name": str(raw.get("name", "Savings")),
            "balance": balance,
            "type": str(raw.get("type", "savings")),
            "include_in_net_cash": bool(raw.get("include_in_net_cash", True)),
            "include_in_runway": bool(raw.get("include_in_runway", False)),
        }
        accounts.append(row)
        total += balance
        if row["include_in_net_cash"]:
            net_cash += balance
        if row["include_in_runway"]:
            runway += balance
    return {
        "accounts": accounts,
        "total": round(total, 2),
        "net_cash": round(net_cash, 2),
        "runway_accessible": round(runway, 2),
    }

def calculate_runway(available_cash: float, accessible_savings: float,
                     monthly_spend: float) -> dict:
    if monthly_spend <= 0:
        return {
            "cash_days": None, "savings_days": None,
            "total_days": None, "total_months": None
        }
    daily = monthly_spend / 30.44
    cash_days = max(0.0, available_cash) / daily
    savings_days = max(0.0, accessible_savings) / daily
    total_days = cash_days + savings_days
    return {
        "cash_days": round(cash_days),
        "savings_days": round(savings_days),
        "total_days": round(total_days),
        "total_months": round(total_days / 30.44, 1),
    }

def money(v: float) -> str:
    return f"£{v:,.2f}"

def savings_receipt_lines(data: dict) -> list[str]:
    t = savings_totals(data)
    if not t["accounts"]:
        return []
    lines = ["SAVINGS", "-" * 42]
    for a in t["accounts"]:
        lines.append(f"{a['name'][:27].upper():<27}{money(a['balance']):>15}")
    lines.append(f"{'TOTAL':<27}{money(t['total']):>15}")
    return lines

def runway_receipt_lines(available_cash: float, savings_data: dict,
                         monthly_spend: float) -> list[str]:
    t = savings_totals(savings_data)
    r = calculate_runway(available_cash, t["runway_accessible"], monthly_spend)
    if r["cash_days"] is None:
        return []
    return [
        "RUNWAY",
        "-" * 42,
        f"{'AVAILABLE CASH':<28}{r['cash_days']:>9} DAYS",
        f"{'+ ACCESSIBLE SAVINGS':<28}{r['savings_days']:>9} DAYS",
        "-" * 42,
        f"{'TOTAL RUNWAY':<28}{r['total_days']:>9} DAYS",
        f"{'':<28}{r['total_months']:>9.1f} MONTHS",
    ]

def savings_snapshot(data: dict) -> dict:
    t = savings_totals(data)
    return {
        "savings_total": t["total"],
        "savings_in_net_cash": t["net_cash"],
        "accessible_runway_savings": t["runway_accessible"],
        "savings_accounts": [
            {"name": a["name"], "balance": a["balance"], "type": a["type"]}
            for a in t["accounts"]
        ],
    }
