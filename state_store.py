from __future__ import annotations

import json
import os
import sqlite3
import threading
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_FILE = DATA_DIR / "receipt_control.db"

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


class StateStoreError(RuntimeError):
    pass


def _connect():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DB_FILE,
        timeout=3.0,
    )

    try:
        os.chmod(
            DB_FILE,
            0o600,
        )
    except OSError:
        pass

    connection.row_factory = sqlite3.Row
    if not _SCHEMA_READY:
        connection.execute(
            "PRAGMA journal_mode=WAL"
        )

    connection.execute(
        "PRAGMA synchronous=NORMAL"
    )
    connection.execute(
        "PRAGMA busy_timeout=3000"
    )
    connection.execute(
        "PRAGMA foreign_keys=ON"
    )

    _ensure_schema(
        connection
    )

    return connection


def _ensure_schema(connection):
    global _SCHEMA_READY

    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                namespace TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                schedule_type TEXT NOT NULL,
                weekday TEXT,
                interval_days INTEGER,
                show_days_before INTEGER NOT NULL DEFAULT 0,
                start_date TEXT,
                last_completed TEXT
            );

            CREATE TABLE IF NOT EXISTS freezer_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                portions INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                added TEXT,
                use_by TEXT,
                batch_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_freezer_name
            ON freezer_items(name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS pantry_items (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                present INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS meal_actions (
                action_key TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                portions_made INTEGER NOT NULL,
                portions_eaten INTEGER NOT NULL,
                frozen INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS migrations (
                name TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL
            );
            """
        )

        connection.commit()
        _migrate_legacy_json(
            connection
        )
        _SCHEMA_READY = True


def _now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def _read_json_for_migration(path, default):
    if not path.exists():
        return deepcopy(
            default
        )

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise StateStoreError(
            f"Could not migrate {path}: {error}"
        ) from error


def _migration_done(connection, name):
    return (
        connection.execute(
            """
            SELECT 1
            FROM migrations
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        is not None
    )


def _mark_migration(connection, name):
    connection.execute(
        """
        INSERT OR REPLACE INTO migrations(
            name,
            completed_at
        )
        VALUES (?, ?)
        """,
        (
            name,
            _now(),
        ),
    )


def _migrate_legacy_json(connection):
    name = "legacy_json_v1"

    if _migration_done(
        connection,
        name,
    ):
        return

    receipt = _read_json_for_migration(
        DATA_DIR / "receipt_settings.json",
        None,
    )

    if (
        receipt is not None
        and connection.execute(
            """
            SELECT 1
            FROM app_state
            WHERE namespace = 'receipt_settings'
            """
        ).fetchone()
        is None
    ):
        _set_state_on_connection(
            connection,
            "receipt_settings",
            receipt,
        )

    printer = _read_json_for_migration(
        DATA_DIR / "printer_settings.json",
        None,
    )

    if (
        printer is not None
        and connection.execute(
            """
            SELECT 1
            FROM app_state
            WHERE namespace = 'printer_settings'
            """
        ).fetchone()
        is None
    ):
        _set_state_on_connection(
            connection,
            "printer_settings",
            printer,
        )

    routines = _read_json_for_migration(
        DATA_DIR / "routines.json",
        [],
    )

    if (
        isinstance(
            routines,
            list,
        )
        and connection.execute(
            "SELECT COUNT(*) FROM routines"
        ).fetchone()[0]
        == 0
    ):
        for item in routines:
            if not isinstance(
                item,
                dict,
            ):
                continue

            connection.execute(
                """
                INSERT OR IGNORE INTO routines(
                    id,
                    name,
                    enabled,
                    schedule_type,
                    weekday,
                    interval_days,
                    show_days_before,
                    start_date,
                    last_completed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(
                        item.get(
                            "id"
                        )
                        or uuid4().hex
                    ),
                    str(
                        item.get(
                            "name",
                            "",
                        )
                    ),
                    1 if item.get(
                        "enabled",
                        True,
                    ) else 0,
                    str(
                        item.get(
                            "schedule_type",
                            "",
                        )
                    ),
                    item.get(
                        "weekday"
                    ),
                    item.get(
                        "interval_days"
                    ),
                    int(
                        item.get(
                            "show_days_before",
                            0,
                        )
                        or 0
                    ),
                    item.get(
                        "start_date"
                    ),
                    item.get(
                        "last_completed"
                    ),
                ),
            )

    freezer = _read_json_for_migration(
        DATA_DIR / "freezer.json",
        {
            "items": [],
        },
    )

    freezer_items = (
        freezer.get(
            "items",
            [],
        )
        if isinstance(
            freezer,
            dict,
        )
        else []
    )

    if (
        connection.execute(
            "SELECT COUNT(*) FROM freezer_items"
        ).fetchone()[0]
        == 0
    ):
        for item in freezer_items:
            if not isinstance(
                item,
                dict,
            ):
                continue

            connection.execute(
                """
                INSERT INTO freezer_items(
                    name,
                    portions,
                    source,
                    added,
                    use_by,
                    batch_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(
                        item.get(
                            "name",
                            "",
                        )
                    ),
                    int(
                        item.get(
                            "portions",
                            0,
                        )
                        or 0
                    ),
                    item.get(
                        "source"
                    ),
                    item.get(
                        "added"
                    ),
                    item.get(
                        "use_by"
                    ),
                    item.get(
                        "batch_id"
                    ),
                ),
            )

    pantry = _read_json_for_migration(
        DATA_DIR / "pantry.json",
        {
            "items": {},
        },
    )

    pantry_items = (
        pantry.get(
            "items",
            {},
        )
        if isinstance(
            pantry,
            dict,
        )
        else {}
    )

    if (
        connection.execute(
            "SELECT COUNT(*) FROM pantry_items"
        ).fetchone()[0]
        == 0
        and isinstance(
            pantry_items,
            dict,
        )
    ):
        for item_name, present in pantry_items.items():
            connection.execute(
                """
                INSERT OR REPLACE INTO pantry_items(
                    name,
                    present
                )
                VALUES (?, ?)
                """,
                (
                    str(
                        item_name
                    ),
                    1 if present else 0,
                ),
            )

    meal_actions = _read_json_for_migration(
        DATA_DIR / "meal_actions.json",
        {
            "actions": {},
        },
    )

    actions = (
        meal_actions.get(
            "actions",
            {},
        )
        if isinstance(
            meal_actions,
            dict,
        )
        else {}
    )

    if (
        connection.execute(
            "SELECT COUNT(*) FROM meal_actions"
        ).fetchone()[0]
        == 0
        and isinstance(
            actions,
            dict,
        )
    ):
        for action_key, item in actions.items():
            if not isinstance(
                item,
                dict,
            ):
                continue

            connection.execute(
                """
                INSERT OR REPLACE INTO meal_actions(
                    action_key,
                    status,
                    recorded_at,
                    portions_made,
                    portions_eaten,
                    frozen
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(
                        action_key
                    ),
                    str(
                        item.get(
                            "status",
                            "completed",
                        )
                    ),
                    str(
                        item.get(
                            "recorded_at",
                            _now(),
                        )
                    ),
                    int(
                        item.get(
                            "portions_made",
                            0,
                        )
                        or 0
                    ),
                    int(
                        item.get(
                            "portions_eaten",
                            0,
                        )
                        or 0
                    ),
                    int(
                        item.get(
                            "frozen",
                            0,
                        )
                        or 0
                    ),
                ),
            )

    _mark_migration(
        connection,
        name,
    )

    connection.commit()


def _set_state_on_connection(
    connection,
    namespace,
    value,
):
    connection.execute(
        """
        INSERT INTO app_state(
            namespace,
            value_json,
            updated_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(namespace) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (
            namespace,
            json.dumps(
                value,
                ensure_ascii=False,
            ),
            _now(),
        ),
    )


def get_state(namespace, default):
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT value_json
            FROM app_state
            WHERE namespace = ?
            """,
            (
                namespace,
            ),
        ).fetchone()

    if row is None:
        return deepcopy(
            default
        )

    try:
        return json.loads(
            row["value_json"]
        )
    except json.JSONDecodeError as error:
        raise StateStoreError(
            f"Invalid state stored for {namespace}: {error}"
        ) from error


def set_state(namespace, value):
    with _connect() as connection:
        _set_state_on_connection(
            connection,
            namespace,
            value,
        )


def update_state(
    namespace,
    default,
    updater,
):
    """
    Atomically read, mutate and write one JSON-backed
    state namespace inside a SQLite transaction.
    """
    connection = _connect()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        row = connection.execute(
            """
            SELECT value_json
            FROM app_state
            WHERE namespace = ?
            """,
            (
                namespace,
            ),
        ).fetchone()

        if row is None:
            value = deepcopy(
                default
            )
        else:
            try:
                value = json.loads(
                    row[
                        "value_json"
                    ]
                )
            except json.JSONDecodeError as error:
                raise StateStoreError(
                    f"Invalid state stored for {namespace}: {error}"
                ) from error

        result = updater(
            value
        )

        _set_state_on_connection(
            connection,
            namespace,
            value,
        )

        connection.commit()
        return result

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def list_routines():
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM routines
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "enabled": bool(
                row["enabled"]
            ),
            "schedule_type":
                row["schedule_type"],
            "weekday":
                row["weekday"],
            "interval_days":
                row["interval_days"],
            "show_days_before":
                row["show_days_before"],
            "start_date":
                row["start_date"],
            "last_completed":
                row["last_completed"],
        }
        for row in rows
    ]


def add_routine_row(item):
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO routines(
                id,
                name,
                enabled,
                schedule_type,
                weekday,
                interval_days,
                show_days_before,
                start_date,
                last_completed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["name"],
                1 if item.get(
                    "enabled",
                    True,
                ) else 0,
                item[
                    "schedule_type"
                ],
                item.get(
                    "weekday"
                ),
                item.get(
                    "interval_days"
                ),
                int(
                    item.get(
                        "show_days_before",
                        0,
                    )
                    or 0
                ),
                item.get(
                    "start_date"
                ),
                item.get(
                    "last_completed"
                ),
            ),
        )


def set_routine_completed(
    routine_id,
    completed_on,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE routines
            SET last_completed = ?
            WHERE id = ?
            """,
            (
                completed_on,
                routine_id,
            ),
        )
        return cursor.rowcount > 0


def set_routine_enabled(
    routine_id,
    enabled,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE routines
            SET enabled = ?
            WHERE id = ?
            """,
            (
                1 if enabled else 0,
                routine_id,
            ),
        )
        return cursor.rowcount > 0


def delete_routine_row(
    routine_id,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            DELETE FROM routines
            WHERE id = ?
            """,
            (
                routine_id,
            ),
        )
        return cursor.rowcount > 0


def list_freezer_items():
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                portions,
                source,
                added,
                use_by,
                batch_id
            FROM freezer_items
            ORDER BY name COLLATE NOCASE, id
            """
        ).fetchall()

    return [
        dict(
            row
        )
        for row in rows
    ]


def add_freezer_item(
    name,
    portions,
    source="manual",
    added=None,
    use_by=None,
    batch_id=None,
):
    with _connect() as connection:
        existing = connection.execute(
            """
            SELECT id, portions
            FROM freezer_items
            WHERE name = ? COLLATE NOCASE
            ORDER BY id
            LIMIT 1
            """,
            (
                name,
            ),
        ).fetchone()

        if existing:
            connection.execute(
                """
                UPDATE freezer_items
                SET portions = ?,
                    source = COALESCE(NULLIF(?, ''), source)
                WHERE id = ?
                """,
                (
                    int(
                        existing[
                            "portions"
                        ]
                    )
                    + int(
                        portions
                    ),
                    source,
                    existing["id"],
                ),
            )

            return int(
                existing[
                    "id"
                ]
            )

        cursor = connection.execute(
            """
            INSERT INTO freezer_items(
                name,
                portions,
                source,
                added,
                use_by,
                batch_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                max(
                    0,
                    int(
                        portions
                    ),
                ),
                source,
                added
                or date.today().isoformat(),
                use_by,
                batch_id,
            ),
        )

        return int(
            cursor.lastrowid
        )


def update_freezer_item(
    item_id,
    *,
    name,
    portions,
    source,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE freezer_items
            SET name = ?,
                portions = ?,
                source = ?
            WHERE id = ?
            """,
            (
                name,
                max(
                    0,
                    int(
                        portions
                    ),
                ),
                source,
                int(
                    item_id
                ),
            ),
        )
        return cursor.rowcount > 0


def delete_freezer_item(
    item_id,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            DELETE FROM freezer_items
            WHERE id = ?
            """,
            (
                int(
                    item_id
                ),
            ),
        )
        return cursor.rowcount > 0


def use_freezer_item(
    item_id,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE freezer_items
            SET portions = portions - 1
            WHERE id = ?
              AND portions > 0
            """,
            (
                int(
                    item_id
                ),
            ),
        )
        return cursor.rowcount > 0


def use_freezer_named(
    name,
):
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM freezer_items
            WHERE name = ? COLLATE NOCASE
              AND portions > 0
            ORDER BY
                CASE
                    WHEN use_by IS NULL OR use_by = ''
                    THEN 1
                    ELSE 0
                END,
                use_by,
                id
            LIMIT 1
            """,
            (
                name,
            ),
        ).fetchone()

        if not row:
            return False

        cursor = connection.execute(
            """
            UPDATE freezer_items
            SET portions = portions - 1
            WHERE id = ?
              AND portions > 0
            """,
            (
                row["id"],
            ),
        )

        return cursor.rowcount > 0


def get_pantry_items():
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT name, present
            FROM pantry_items
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()

    return {
        row["name"]: bool(
            row["present"]
        )
        for row in rows
    }


def set_pantry_item(
    name,
    present,
):
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO pantry_items(
                name,
                present
            )
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET
                present = excluded.present
            """,
            (
                name,
                1 if present else 0,
            ),
        )


def delete_pantry_item(
    name,
):
    with _connect() as connection:
        cursor = connection.execute(
            """
            DELETE FROM pantry_items
            WHERE name = ? COLLATE NOCASE
            """,
            (
                name,
            ),
        )
        return cursor.rowcount > 0


def get_meal_action(
    action_key,
):
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM meal_actions
            WHERE action_key = ?
            """,
            (
                action_key,
            ),
        ).fetchone()

    return (
        dict(
            row
        )
        if row
        else None
    )


def begin_meal_action(
    action_key,
    *,
    portions_made,
    portions_eaten,
    frozen,
    replace=False,
):
    with _connect() as connection:
        if replace:
            connection.execute(
                """
                DELETE FROM meal_actions
                WHERE action_key = ?
                """,
                (
                    action_key,
                ),
            )

        try:
            connection.execute(
                """
                INSERT INTO meal_actions(
                    action_key,
                    status,
                    recorded_at,
                    portions_made,
                    portions_eaten,
                    frozen
                )
                VALUES (?, 'processing', ?, ?, ?, ?)
                """,
                (
                    action_key,
                    _now(),
                    int(
                        portions_made
                    ),
                    int(
                        portions_eaten
                    ),
                    int(
                        frozen
                    ),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def complete_meal_action(
    action_key,
):
    with _connect() as connection:
        connection.execute(
            """
            UPDATE meal_actions
            SET status = 'completed'
            WHERE action_key = ?
            """,
            (
                action_key,
            ),
        )


def delete_meal_action(
    action_key,
):
    with _connect() as connection:
        connection.execute(
            """
            DELETE FROM meal_actions
            WHERE action_key = ?
            """,
            (
                action_key,
            ),
        )


def database_health():
    with _connect() as connection:
        integrity = connection.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]

        counts = {
            "freezer":
                connection.execute(
                    "SELECT COUNT(*) FROM freezer_items"
                ).fetchone()[0],
            "pantry":
                connection.execute(
                    "SELECT COUNT(*) FROM pantry_items"
                ).fetchone()[0],
            "routines":
                connection.execute(
                    "SELECT COUNT(*) FROM routines"
                ).fetchone()[0],
        }

    return {
        "ok": integrity == "ok",
        "integrity": integrity,
        "counts": counts,
        "path": str(
            DB_FILE
        ),
    }
