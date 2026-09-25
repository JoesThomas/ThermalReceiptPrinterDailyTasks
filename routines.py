from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from data_store import edit_json, read_json

PROJECT_ROOT = Path(__file__).resolve().parent
ROUTINES_FILE = PROJECT_ROOT / "data" / "routines.json"

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def load_routines():
    data = read_json(
        ROUTINES_FILE,
        [],
    )

    if not isinstance(data, list):
        raise ValueError(
            "data/routines.json must contain a JSON list."
        )

    return data


def add_routine(
    name,
    schedule_type,
    *,
    weekday=None,
    interval_days=None,
    show_days_before=0,
    enabled=True,
):
    with edit_json(
        ROUTINES_FILE,
        [],
    ) as routines:
        item = {
            "id": uuid4().hex,
            "name": str(name).strip(),
            "enabled": bool(enabled),
            "schedule_type": schedule_type,
            "weekday": weekday,
            "interval_days": interval_days,
            "show_days_before": max(
                0,
                int(
                    show_days_before
                    or 0
                ),
            ),
            "start_date": date.today().isoformat(),
            "last_completed": None,
        }

        routines.append(
            item
        )

        return item


def _as_date(value):
    try:
        return (
            date.fromisoformat(
                str(value)
            )
            if value
            else None
        )
    except ValueError:
        return None


def next_due_date(
    routine,
    today=None,
):
    today = (
        today
        or date.today()
    )

    kind = routine.get(
        "schedule_type"
    )

    if kind == "weekly":
        weekday = str(
            routine.get(
                "weekday"
            )
            or ""
        ).lower()

        if weekday not in WEEKDAYS:
            return None

        return today + timedelta(
            days=(
                WEEKDAYS.index(
                    weekday
                )
                - today.weekday()
            )
            % 7
        )

    if kind == "interval":
        try:
            days = max(
                1,
                int(
                    routine.get(
                        "interval_days"
                    )
                    or 1
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

        last = _as_date(
            routine.get(
                "last_completed"
            )
        )

        return (
            last + timedelta(
                days=days
            )
            if last
            else (
                _as_date(
                    routine.get(
                        "start_date"
                    )
                )
                or today
            )
        )

    return None


def routine_is_visible(
    routine,
    today=None,
):
    if not routine.get(
        "enabled",
        True,
    ):
        return False

    today = (
        today
        or date.today()
    )

    due = next_due_date(
        routine,
        today,
    )

    if not due:
        return False

    try:
        before = max(
            0,
            int(
                routine.get(
                    "show_days_before"
                )
                or 0
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        before = 0

    return (
        today
        >= due
        - timedelta(
            days=before
        )
    )


def due_routines(
    today=None,
):
    today = (
        today
        or date.today()
    )

    output = []

    for routine in load_routines():
        if routine_is_visible(
            routine,
            today,
        ):
            item = dict(
                routine
            )

            item["next_due"] = (
                next_due_date(
                    routine,
                    today,
                )
                .isoformat()
            )

            output.append(
                item
            )

    return output


def mark_done(
    routine_id,
    completed_on=None,
):
    completed_on = (
        completed_on
        or date.today()
    )

    found = False

    with edit_json(
        ROUTINES_FILE,
        [],
    ) as routines:
        for item in routines:
            if (
                item.get("id")
                == routine_id
            ):
                item[
                    "last_completed"
                ] = completed_on.isoformat()

                found = True
                break

    return found


def delete_routine(
    routine_id,
):
    removed = False

    with edit_json(
        ROUTINES_FILE,
        [],
    ) as routines:
        for index in range(
            len(routines) - 1,
            -1,
            -1,
        ):
            if (
                routines[index].get(
                    "id"
                )
                == routine_id
            ):
                del routines[index]
                removed = True

    return removed


def set_enabled(
    routine_id,
    enabled,
):
    found = False

    with edit_json(
        ROUTINES_FILE,
        [],
    ) as routines:
        for item in routines:
            if (
                item.get("id")
                == routine_id
            ):
                item["enabled"] = bool(
                    enabled
                )
                found = True
                break

    return found
