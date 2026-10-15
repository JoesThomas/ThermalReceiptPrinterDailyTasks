"""Bank balance provenance shared by both test receipt layouts."""

from decimal import Decimal

from finance.projection import money

ZERO = Decimal(0)


def bank_balances(page, projection):
    if "bank_balance_sources" not in projection:
        return
    sources = projection["bank_balance_sources"]
    if sources:
        page.section("CONNECTED BANK BALANCES")
        total = ZERO
        complete = True
        for provider in ("HSBC", "MONZO"):
            row = sources.get(provider, {})
            for account in row.get("accounts", []):
                name = " ".join(str(account.get("name", "Account")).split())
                page.amount(
                    f"{provider} - {name}", money(account.get("available"), ZERO)
                )
            balance = money(row.get("available", row.get("current")))
            if balance is None:
                complete = False
                page.text(f"{provider} balance unavailable")
                continue
            page.amount(f"{provider} total", balance)
            total += balance
            if row.get("scope") == "First account (default)":
                page.text(f"{provider}: first account default; check selection.")
            if row.get("checked_at"):
                page.text("Checked: " + str(row["checked_at"]))
        page.amount(
            "Combined bank balance" if complete else "Combined known bank balance",
            total,
        )
        page.text(
            "Available balances before planned transfers. Confirm selected accounts in Finance."
        )
    if projection.get("bank_cash_manual") or not sources:
        page.section("STARTING BANK BALANCES")
        monzo = projection.get("monzo_balance", ZERO)
        page.amount("HSBC (scenario)", projection["cash"] - monzo)
        page.amount("Monzo (scenario)", monzo)
        page.amount("Combined bank cash used", projection["cash"])
        page.text("Manual starting cash; not a connected balance.")
    elif projection.get("monzo_target"):
        connected = money(
            sources.get("MONZO", {}).get(
                "available", sources.get("MONZO", {}).get("current")
            ),
            ZERO,
        )
        if projection.get("monzo_balance", ZERO) != connected:
            page.amount("Starting Monzo override", projection["monzo_balance"])
            page.text("Manual Monzo split; combined bank cash unchanged.")
