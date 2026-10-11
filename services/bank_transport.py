"""TrueLayer authentication and bounded reads, separate from receipt rendering."""

from datetime import datetime, timedelta, timezone
from services import bank_session
from services.observability import timed
from storage import file_lock


def refresh(
    provider,
    *,
    token_file,
    initial,
    load_tokens,
    save_tokens,
    client_id,
    client_secret,
    auth_url,
    http,
):
    def load():
        if not client_id or not client_secret:
            raise RuntimeError("TrueLayer client credentials are not configured")
        # Rotation is a read/refresh/write transaction, including other processes.
        with file_lock(token_file):
            refresh_token = initial(provider)
            if not refresh_token:
                raise RuntimeError("TrueLayer connection is not configured")
            with timed("token_refresh", provider=provider):
                response = http.post(
                    auth_url,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                    },
                    timeout=20,
                )
                response.raise_for_status()
                payload = response.json()
                access = payload.get("access_token")
                if not access:
                    raise RuntimeError("TrueLayer returned no access token")
                replacement = payload.get("refresh_token")
                if replacement:
                    tokens = load_tokens()
                    tokens[provider] = replacement
                    save_tokens(tokens)
                return access

    return bank_session.access_token(provider, load)


def get(access_token, endpoint, *, data_url, http):
    def load():
        resource = endpoint.rsplit("/", 1)[-1]
        if resource not in {
            "accounts",
            "cards",
            "balance",
            "direct_debits",
            "standing_orders",
            "transactions",
        }:
            resource = "account data"
        bank_session.stage(
            f"Retrieving {bank_session.provider() or 'bank'} {resource.replace('_', ' ')}"
        )
        with timed(
            "bank_read_" + resource.replace(" ", "_"), provider=bank_session.provider()
        ):
            response = http.get(
                f"{data_url}{endpoint}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            response.raise_for_status()
            return response.json()

    return bank_session.account_list(access_token, endpoint, load)


def transactions(
    access_token,
    endpoint_prefix,
    account_id,
    from_date,
    to_date,
    *,
    data_url,
    http,
    timeout=20,
    range_info=None,
    now=None,
):
    end = min(to_date, now or datetime.now(timezone.utc).date())
    start = max(from_date, end - timedelta(days=89))

    def fetch(first, last):
        bank_session.stage(
            f"Retrieving {bank_session.provider() or 'bank'} transactions"
        )
        with timed("bank_transactions", provider=bank_session.provider()):
            response = http.get(
                f"{data_url}/{endpoint_prefix}/{account_id}/transactions",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"from": first.isoformat(), "to": last.isoformat()},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json().get("results", [])

    try:
        return fetch(start, end)
    except http.HTTPError as error:
        response = getattr(error, "response", None)
        try:
            code = response.json().get("error")
        except (AttributeError, ValueError):
            code = None
        if (
            response is None
            or response.status_code != 400
            or code != "invalid_date_range"
        ):
            raise
        if range_info is not None:
            range_info["shortened"] = True
        return fetch(max(from_date, end - timedelta(days=29)), end)
