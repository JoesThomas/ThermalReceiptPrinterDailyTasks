"""Read-only, redacted TrueLayer finance diagnostic for support."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo


def _safe_type(value):
    kind = str(value or "missing").upper()
    return kind if kind in {"CREDIT", "DEBIT", "CARD_PAYMENT", "MISSING"} else "OTHER"


def _error_code(error):
    try:
        payload = error.response.json()
    except (AttributeError, ValueError):
        return "unknown"
    value = payload.get("error") if isinstance(payload, dict) else None
    # Restrict output to documented codes; never print provider response text.
    allowed = {"invalid_date_range", "validation_error", "access_denied",
               "sca_exceeded", "invalid_token", "unauthorized",
               "provider_request_limit_exceeded"}
    return value if isinstance(value, str) and value in allowed else "other"


def run_finance_debug():
    from services import live_pipeline as finance

    today = datetime.now(ZoneInfo("Europe/London")).date()
    start = today - timedelta(days=finance.FINANCE_TRANSACTION_LOOKBACK_DAYS)
    cutoff = today - timedelta(days=30)
    print("FINANCE DEBUG (REDACTED)")
    print(f"Window: {start} to {today}")
    transactions = []
    failures = 0
    successes = 0
    probed = set()
    for provider in ("HSBC", "MONZO", "AMEX"):
        try:
            # The service prints raw provider errors, which may contain URLs
            # or sensitive metadata. Discard that output in this diagnostic.
            with redirect_stdout(StringIO()):
                token = finance._refresh_truelayer_access_token(
                    provider, finance._initial_truelayer_refresh_token(provider))
        except Exception as error:
            failures += 1
            print(f"Source: provider={provider} stage=token error={type(error).__name__}")
            continue
        try:
            with redirect_stdout(StringIO()):
                ids = (finance._truelayer_card_ids(token) if provider == "AMEX"
                       else finance._truelayer_account_ids(token))
        except Exception as error:
            failures += 1
            code = getattr(getattr(error, "response", None), "status_code", None)
            print(f"Source: provider={provider} stage=list http={code}")
            continue
        if not ids:
            failures += 1
            print(f"Source: provider={provider} stage=list count=0")
        for index, account_id in enumerate(ids, 1):
            try:
                with redirect_stdout(StringIO()):
                    items = finance._truelayer_transactions(
                        token, "cards" if provider == "AMEX" else "accounts",
                        account_id, start, today)
            except Exception as error:
                failures += 1
                code = getattr(getattr(error, "response", None), "status_code", None)
                print(f"Source: provider={provider} source={index} stage=transactions http={code} error={_error_code(error)}")
                if code == 400 and provider not in probed:
                    probed.add(provider)
                    # Probe a smaller, ended-in-UTC window to distinguish date
                    # validation from authorization or provider failures.
                    probe_end = min(today, datetime.now(ZoneInfo("UTC")).date())
                    probe_start = probe_end - timedelta(days=29)
                    try:
                        with redirect_stdout(StringIO()):
                            items = finance._truelayer_transactions(
                                token, "cards" if provider == "AMEX" else "accounts",
                                account_id, probe_start, probe_end)
                    except Exception as probe_error:
                        probe_http = getattr(getattr(probe_error, "response", None), "status_code", None)
                        print(f"Probe: provider={provider} source={index} window=30d "
                              f"http={probe_http} error={_error_code(probe_error)}")
                    else:
                        successes += 1
                        transactions.extend(items)
                        print(f"Probe: provider={provider} source={index} window=30d "
                              f"count={len(items)} credits={sum(finance._is_incoming_transaction(tx) for tx in items)}")
                continue
            successes += 1
            transactions.extend(items)
            print(f"Source: provider={provider} source={index} stage=transactions "
                  f"count={len(items)} credits={sum(finance._is_incoming_transaction(tx) for tx in items)}")

    state = "unavailable" if not successes else "partial" if failures else "complete"
    print("Bank data:", state)
    print("Transactions fetched:", len(transactions))
    with redirect_stdout(StringIO()):
        salary, other = finance.analyse_incoming_payments(
            transactions, salary_payee=finance.load_receipt_settings()
            .get("finance", {}).get("salary_payee", ""))
    print(f"Incoming classified: {len(salary)} salary, {len(other)} other")
    print("Incoming last 30 days:", sum(cutoff <= item["date"] <= today
                                          for item in salary + other))
    candidates = [tx for tx in transactions
                  if abs(abs(finance._safe_amount(tx.get("amount"))) - 800) < 0.01]
    print("GBP 800 candidates:", len(candidates))
    for tx in candidates:
        day = finance._transaction_date(tx)
        amount = finance._safe_amount(tx.get("amount"))
        print("Candidate: date={} amount_sign={} type={} incoming={} internal_transfer={} "
              "salary={} category={} within_30_days={}".format(
                  day.isoformat() if day else "missing",
                  "positive" if amount > 0 else "negative", _safe_type(tx.get("transaction_type")),
                  finance._is_incoming_transaction(tx), finance._looks_like_internal_transfer(tx),
                  finance._looks_like_salary(tx, finance.load_receipt_settings()
                                             .get("finance", {}).get("salary_payee", "")),
                  finance._other_incoming_category(tx), bool(day and cutoff <= day <= today)))
    with redirect_stdout(StringIO()):
        monthly = finance.build_subscription_status(transactions, today=today)["monthly"]
    print("Monthly commitments: {} paid / {} unmatched".format(
        sum(bool(item["paid"]) for item in monthly),
        sum(not item["paid"] for item in monthly)))
    print("Share this diagnostic output. Do not share raw TrueLayer errors or token files.")
