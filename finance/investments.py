import json
from datetime import date, datetime
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_INVESTMENTS_FILE = (
    PROJECT_ROOT
    / "data"
    / "investments.json"
)


def load_investments(
    path=DEFAULT_INVESTMENTS_FILE,
):
    path = Path(path)

    if not path.exists():
        return {
            "updated": None,
            "accounts": [],
        }

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {
            "updated": None,
            "accounts": [],
        }

    if not isinstance(data, dict):
        return {
            "updated": None,
            "accounts": [],
        }

    accounts = data.get(
        "accounts",
        [],
    )

    if not isinstance(
        accounts,
        list,
    ):
        accounts = []

    return {
        "updated": data.get(
            "updated"
        ),
        "accounts": accounts,
    }


def investment_totals(data):
    accounts = data.get(
        "accounts",
        [],
    )

    value = 0.0
    contributions = 0.0

    for account in accounts:
        try:
            value += float(
                account.get(
                    "value",
                    0,
                )
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

        try:
            contributions += float(
                account.get(
                    "contributions",
                    0,
                )
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    gain = (
        value
        - contributions
    )

    gain_pct = (
        gain
        / contributions
        * 100
        if contributions > 0
        else None
    )

    return {
        "value": round(
            value,
            2,
        ),
        "contributions": round(
            contributions,
            2,
        ),
        "gain": round(
            gain,
            2,
        ),
        "gain_pct": (
            round(
                gain_pct,
                1,
            )
            if gain_pct is not None
            else None
        ),
    }


def investment_age_days(
    data,
    today=None,
):
    today = today or date.today()

    value = data.get(
        "updated"
    )

    if not value:
        return None

    try:
        updated = (
            datetime.strptime(
                value,
                "%Y-%m-%d",
            )
            .date()
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    return (
        today - updated
    ).days


def investment_snapshot(data):
    totals = investment_totals(
        data
    )

    return {
        "updated": data.get(
            "updated"
        ),
        "total_value": totals[
            "value"
        ],
        "contributions": totals[
            "contributions"
        ],
    }