"""Page visibility shared by the Amex banners and their polling responses."""

from flask import request, session


def scope():
    if not session.get("authenticated"):
        return None
    if request.endpoint == "finance_review" or request.path.startswith("/finance/"):
        return "finance"
    if (
        request.endpoint == "index"
        and request.args.get("view", "dashboard") == "dashboard"
    ):
        return "home"
    return None


def balance_for(page):
    from finance.amex_balance import view

    balance = view()
    if page == "home":
        balance = {**balance, "show": balance["show"] and balance["level"] == "high"}
    return balance
