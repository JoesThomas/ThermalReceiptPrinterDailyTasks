"""Request-scoped token and account-list reuse; no credentials persisted here."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from time import monotonic

CURRENT = ContextVar("bank_retrieval_session", default=None)


@contextmanager
def retrieval(*, progress=None, timeout=600):
    existing = CURRENT.get()
    if existing is not None:
        yield existing
        return
    state = {
        "tokens": {},
        "responses": {},
        "progress": progress,
        "deadline": monotonic() + timeout,
    }
    token = CURRENT.set(state)
    try:
        yield state
    finally:
        CURRENT.reset(token)


def stage(message, *, provider=None):
    state = CURRENT.get()
    if state is not None:
        if provider is not None:
            state["provider"] = provider
        if monotonic() >= state["deadline"]:
            raise TimeoutError("Bank retrieval time limit reached")
        if state["progress"]:
            state["progress"](message)


def provider():
    state = CURRENT.get()
    return state.get("provider") if state else None


def access_token(provider, load):
    stage(f"Connecting to {provider}", provider=provider)
    state = CURRENT.get()
    if state is None:
        return load()
    if provider not in state["tokens"]:
        try:
            state["tokens"][provider] = load()
        except Exception as error:
            state["tokens"][provider] = error
    result = state["tokens"][provider]
    if isinstance(result, Exception):
        raise result
    return result


def account_list(token, endpoint, load):
    # Only inventories are reused. Balances and transactions remain fresh reads.
    state = CURRENT.get()
    if state is None or endpoint not in {"/accounts", "/cards"}:
        return load()
    key = (token, endpoint)
    if key not in state["responses"]:
        state["responses"][key] = load()
    return deepcopy(state["responses"][key])


def collect_snapshot(pipeline, *, progress=None, persist=True, today=None):
    from services.finance_source import collect, dependencies_from
    from services.observability import event, timed

    with retrieval(progress=progress):
        with timed("finance_collection"):
            data = collect(dependencies_from(pipeline, today=today), persist=persist)
            stage("Retrieving current bank balances")
            try:
                balances = pipeline.get_account_balances()
            except Exception as error:
                event("bank_balances", status="failed", error=error)
                balances = {}
            stage("Preparing finance review")
            return {"data": data, "balances": balances}
