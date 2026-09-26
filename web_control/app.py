from __future__ import annotations
import os, subprocess, sys
import shlex
import json
import fcntl
from datetime import date, datetime, timezone
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from receipt_settings import load_receipt_settings, save_receipt_settings
from data_store import JsonDataError, edit_json, read_json, write_json
from state_store import (
    StateStoreError,
    backup_database_if_due,
    add_freezer_item,
    begin_meal_action,
    complete_meal_action,
    database_health,
    delete_freezer_item,
    delete_meal_action,
    delete_pantry_item,
    get_pantry_items,
    list_freezer_items,
    set_pantry_item,
    update_freezer_item,
    update_state,
    use_freezer_item,
)
from routines import WEEKDAYS, add_routine, delete_routine, load_routines, mark_done, next_due_date, set_enabled
from printer_config import (
    check_printer_connection,
    load_printer_settings,
    printer_connection_label,
    save_printer_settings,
)
from meal_planner import (
    add_freezer_portions,
    get_meal,
    record_cooked,
)

app = Flask(__name__)

csrf = CSRFProtect(app)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
)

SUBSCRIPTIONS_FILE = (
    PROJECT_ROOT / "data" / "subscriptions.json"
)

AUDIT_LOG_FILE = (
    PROJECT_ROOT / "logs" / "audit.log"
)

_database_backup_checked = False


def audit_event(action, detail=""):
    AUDIT_LOG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).isoformat()

    safe_detail = str(
        detail
    ).replace(
        "\n",
        " ",
    )[:500]

    line = (
        f"{timestamp}\t{action}\t{safe_detail}\n"
    )

    with AUDIT_LOG_FILE.open(
        "a",
        encoding="utf-8",
    ) as file:
        fcntl.flock(
            file.fileno(),
            fcntl.LOCK_EX,
        )
        try:
            file.write(
                line
            )
            file.flush()
        finally:
            fcntl.flock(
                file.fileno(),
                fcntl.LOCK_UN,
            )


def load_subscriptions():
    data = read_json(
        SUBSCRIPTIONS_FILE,
        {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        },
    )

    if not isinstance(
        data,
        dict,
    ):
        raise JsonDataError(
            "data/subscriptions.json must contain a JSON object."
        )

    data.setdefault(
        "monthly",
        [],
    )
    data.setdefault(
        "yearly",
        [],
    )
    data.setdefault(
        "instalments",
        [],
    )

    return data


def save_subscriptions(data):
    """
    Save subscription and instalment changes
    made through Receipt Control.
    """
    write_json(
        SUBSCRIPTIONS_FILE,
        data,
    )


def _load_json_file(path, default):
    return read_json(
        path,
        default,
    )


def _save_json_file(path, value):
    write_json(
        path,
        value,
    )


def load_freezer():
    return {
        "items":
            list_freezer_items(),
    }


def load_pantry():
    return {
        "items":
            get_pantry_items(),
    }


def data_file_status():
    database = database_health()

    output = [{
        "label": "Receipt database",
        "path": "data/receipt_control.db",
        "exists": True,
        "valid": database["ok"],
        "detail": (
            "SQLite OK · "
            f"{database['counts']['freezer']} freezer · "
            f"{database['counts']['pantry']} pantry · "
            f"{database['counts']['routines']} routines"
        ),
    }]

    files = [
        (
            "Subscriptions",
            SUBSCRIPTIONS_FILE,
        ),
        (
            "Recipe history",
            PROJECT_ROOT
            / "data"
            / "recipe_history.json",
        ),
    ]

    for label, path in files:
        exists = path.exists()
        valid = False
        detail = "Not created yet"

        if exists:
            try:
                value = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )

                valid = isinstance(
                    value,
                    (dict, list),
                )

                if isinstance(
                    value,
                    dict,
                ):
                    detail = (
                        f"{len(value)} top-level fields"
                    )
                elif isinstance(
                    value,
                    list,
                ):
                    detail = (
                        f"{len(value)} records"
                    )

            except (
                OSError,
                json.JSONDecodeError,
            ) as error:
                detail = str(
                    error
                )

        output.append({
            "label": label,
            "path": str(
                path.relative_to(
                    PROJECT_ROOT
                )
            ),
            "exists": exists,
            "valid": valid,
            "detail": detail,
        })

    return output


PROJECT_PASSWORDS_FILE = (
    PROJECT_ROOT / "passwords.json"
)


def _google_doc_id(value):
    text = str(value or "").strip()

    if not text:
        return ""

    if "/document/d/" in text:
        return (
            text.split("/document/d/", 1)[1]
            .split("/", 1)[0]
            .strip()
        )

    return text


def load_food_shop_items():
    """
    Load the configured food-shop Google Doc for the
    Receipt Control page without importing the printer
    pipeline.
    """
    if not PROJECT_PASSWORDS_FILE.exists():
        return [], "Project passwords.json is missing."

    try:
        private = json.loads(
            PROJECT_PASSWORDS_FILE.read_text(
                encoding="utf-8"
            )
        )

        document_value = (
            private
            .get("google_docs", {})
            .get("food_shop_url", "")
        )

        document_id = _google_doc_id(
            document_value
        )

        if not document_id:
            return [], (
                "Food-shop Google Doc is not configured."
            )

        export_url = (
            "https://docs.google.com/document/d/"
            f"{document_id}/export?format=txt"
        )

        with urlopen(
            export_url,
            timeout=15,
        ) as response:
            text = response.read().decode(
                "utf-8",
                errors="replace",
            )

        items = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        return items, None

    except Exception as error:
        return [], str(error)


@app.errorhandler(StateStoreError)
def handle_state_store_error(error):
    return (
        render_template(
            "data_error.html",
            error_message=str(error),
        ),
        500,
    )


@app.errorhandler(JsonDataError)
def handle_json_data_error(error):
    return (
        render_template(
            "data_error.html",
            error_message=str(error),
        ),
        500,
    )


# ============================================================
# PASSWORD
# ============================================================

PASSWORD_FILE = (
    Path(__file__).resolve().parent
    / "passwords.json"
)

def load_password_hash():
    if not PASSWORD_FILE.exists():
        raise RuntimeError(
            "Receipt Control password has not "
            "been configured. Run "
            "web_control/create_password_hash.py"
        )

    try:
        data = json.loads(
            PASSWORD_FILE.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError(
            "Could not read Receipt Control "
            "password file."
        ) from error

    password_hash = str(
        data.get(
            "password_hash",
            ""
        )
    ).strip()

    if not password_hash:
        raise RuntimeError(
            "password_hash is missing from "
            "web_control/passwords.json"
        )

    return password_hash


# ============================================================
# FLASK SECRET KEY
# ============================================================

SECRET_KEY_FILE = (
    Path(__file__).resolve().parent
    / "secret_key.txt"
)

if not SECRET_KEY_FILE.exists():
    raise RuntimeError(
        "Missing web_control/secret_key.txt"
    )

for private_path in (
    SECRET_KEY_FILE,
    PASSWORD_FILE,
    PROJECT_PASSWORDS_FILE,
):
    if private_path.exists():
        try:
            os.chmod(
                private_path,
                0o600,
            )
        except OSError:
            pass

app.secret_key = (
    SECRET_KEY_FILE
    .read_text(
        encoding="utf-8"
    )
    .strip()
)


# ============================================================
# SESSION SETTINGS
# ============================================================

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(
        hours=12
    ),
)

if (
    os.environ.get(
        "RECEIPT_WEB_SECURE_COOKIE"
    )
    == "1"
):
    app.config[
        "SESSION_COOKIE_SECURE"
    ] = True


@app.after_request
def add_security_headers(response):
    response.headers.setdefault(
        "X-Content-Type-Options",
        "nosniff",
    )
    response.headers.setdefault(
        "X-Frame-Options",
        "DENY",
    )
    response.headers.setdefault(
        "Referrer-Policy",
        "no-referrer",
    )
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'",
    )
    return response


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"): return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.post("/meal/today/cooked")
@login_required
def meal_today_cooked():
    meal = get_meal()

    if not meal:
        flash("There is no meal planned for today.")
        return redirect(url_for("index"))

    if meal.get("kind") != "recipe":
        flash(
            "Today's planned meal is not a recipe, "
            "so there is nothing to record as cooked."
        )
        return redirect(url_for("index"))

    recipe = meal.get("recipe", {})
    recipe_name = str(
        recipe.get(
            "name",
            "Recipe",
        )
    ).strip()

    try:
        made = max(
            1,
            int(
                request.form.get(
                    "portions_made",
                    recipe.get(
                        "servings",
                        1,
                    ),
                )
            ),
        )

        eaten = max(
            0,
            int(
                request.form.get(
                    "portions_eaten",
                    "1",
                )
            ),
        )

    except (
        TypeError,
        ValueError,
    ):
        flash("Portions must be whole numbers.")
        return redirect(url_for("index"))

    if eaten > made:
        flash(
            "Portions eaten cannot be greater "
            "than portions made."
        )
        return redirect(url_for("index"))

    frozen = made - eaten

    action_key = (
        f"{date.today().isoformat()}:"
        f"{recipe_name.lower()}"
    )

    force_record = (
        request.form.get(
            "force_record",
            "0",
        )
        == "1"
    )

    started = begin_meal_action(
        action_key,
        portions_made=made,
        portions_eaten=eaten,
        frozen=frozen,
        replace=force_record,
    )

    if not started:
        flash(
            "This meal has already been recorded today. "
            "Use 'Record again' only if that is intentional."
        )
        return redirect(
            url_for("index")
        )

    try:
        record_cooked(
            recipe_name
        )

        if frozen > 0:
            add_freezer_portions(
                recipe_name,
                frozen,
                source="cooked meal leftovers",
            )

    except Exception:
        delete_meal_action(
            action_key
        )
        raise

    complete_meal_action(
        action_key
    )

    if frozen:
        flash(
            f"Recorded {recipe_name} as cooked. "
            f"{eaten} eaten, {frozen} added to freezer."
        )
    else:
        flash(
            f"Recorded {recipe_name} as cooked. "
            f"{eaten} eaten, nothing added to freezer."
        )

    audit_event(
        "meal_recorded",
        f"{recipe_name}; made={made}; eaten={eaten}; frozen={frozen}",
    )

    return redirect(
        url_for("index")
    )


@app.post("/freezer/<int:item_id>/eat-one")
@login_required
def freezer_eat_one(item_id):
    items = list_freezer_items()

    item = next(
        (
            entry
            for entry in items
            if int(
                entry["id"]
            )
            == item_id
        ),
        None,
    )

    if item is None:
        return (
            "Freezer item not found",
            404,
        )

    name = str(
        item.get(
            "name",
            "",
        )
    ).strip()

    if use_freezer_item(
        item_id
    ):
        audit_event(
            "freezer_portion_used",
            name,
        )
        flash(
            f"Used one freezer portion of {name}."
        )
    else:
        flash(
            f"No freezer portions of {name} are available."
        )

    return redirect(
        url_for("index")
    )


@app.post("/printer/settings")
@login_required
def printer_settings_update():
    connection = request.form.get(
        "connection",
        "usb",
    ).strip().lower()

    if connection not in {
        "usb",
        "network",
    }:
        connection = "usb"

    settings = load_printer_settings()
    settings["connection"] = connection

    settings.setdefault(
        "usb",
        {},
    )

    settings["usb"]["vendor_id"] = (
        request.form.get(
            "usb_vendor_id",
            "0x0416",
        ).strip()
        or "0x0416"
    )

    settings["usb"]["product_id"] = (
        request.form.get(
            "usb_product_id",
            "0x5011",
        ).strip()
        or "0x5011"
    )

    settings.setdefault(
        "network",
        {},
    )

    settings["network"]["host"] = (
        request.form.get(
            "network_host",
            "",
        ).strip()
    )

    try:
        port = int(
            request.form.get(
                "network_port",
                "9100",
            )
        )
    except ValueError:
        port = 9100

    settings["network"]["port"] = max(
        1,
        min(
            65535,
            port,
        ),
    )

    save_printer_settings(
        settings
    )

    audit_event(
        "printer_settings_changed",
        printer_connection_label(
            settings
        ),
    )

    flash(
        "Printer connection settings saved."
    )

    return redirect(
        url_for("index")
    )


@app.post("/printer/test")
@login_required
def printer_test():
    status = check_printer_connection()

    audit_event(
        "printer_connection_test",
        (
            "ok " if status["ok"] else "failed "
        )
        + status["label"],
    )

    if status["ok"]:
        flash(
            f"Printer connected: {status['label']}."
        )
    else:
        flash(
            "Printer connection failed: "
            + status["message"]
        )

    return redirect(
        url_for("index")
    )


@app.post("/freezer/add")
@login_required
def freezer_add():
    name = request.form.get(
        "name",
        "",
    ).strip()

    if not name:
        flash(
            "Enter a freezer item name."
        )
        return redirect(
            url_for("index")
        )

    try:
        portions = max(
            0,
            int(
                request.form.get(
                    "portions",
                    "1",
                )
            ),
        )
    except ValueError:
        flash(
            "Freezer portions must be a number."
        )
        return redirect(
            url_for("index")
        )

    source = request.form.get(
        "source",
        "",
    ).strip()

    add_freezer_item(
        name,
        portions,
        source=source or "manual",
        added=date.today().isoformat(),
    )

    audit_event(
        "freezer_item_added",
        name,
    )

    flash(
        f"Freezer updated: {name}."
    )

    return redirect(
        url_for("index")
    )


@app.post("/freezer/<int:item_id>/update")
@login_required
def freezer_update(item_id):
    name = request.form.get(
        "name",
        "",
    ).strip()

    if not name:
        flash(
            "Freezer item name cannot be empty."
        )
        return redirect(
            url_for("index")
        )

    try:
        portions = max(
            0,
            int(
                request.form.get(
                    "portions",
                    "0",
                )
            ),
        )
    except ValueError:
        flash(
            "Freezer portions must be a number."
        )
        return redirect(
            url_for("index")
        )

    updated = update_freezer_item(
        item_id,
        name=name,
        portions=portions,
        source=request.form.get(
            "source",
            "",
        ).strip(),
    )

    if not updated:
        return (
            "Freezer item not found",
            404,
        )

    audit_event(
        "freezer_item_updated",
        name,
    )

    flash(
        f"Freezer item updated: {name}."
    )

    return redirect(
        url_for("index")
    )


@app.post("/freezer/<int:item_id>/delete")
@login_required
def freezer_delete(item_id):
    items = list_freezer_items()

    item = next(
        (
            entry
            for entry in items
            if int(
                entry["id"]
            )
            == item_id
        ),
        None,
    )

    if item is None:
        return (
            "Freezer item not found",
            404,
        )

    name = str(
        item.get(
            "name",
            "item",
        )
    )

    if not delete_freezer_item(
        item_id
    ):
        return (
            "Freezer item not found",
            404,
        )

    audit_event(
        "freezer_item_deleted",
        name,
    )

    flash(
        f"Removed from freezer: {name}."
    )

    return redirect(
        url_for("index")
    )


@app.post("/pantry/item")
@login_required
def pantry_item_update():
    name = request.form.get(
        "name",
        "",
    ).strip()

    if not name:
        flash(
            "Enter a pantry item name."
        )
        return redirect(
            url_for("index")
        )

    present = (
        request.form.get(
            "present",
            "1",
        )
        == "1"
    )

    set_pantry_item(
        name,
        present,
    )

    audit_event(
        "pantry_item_updated",
        f"{name}; present={present}",
    )

    flash(
        f"Pantry updated: {name}."
    )

    return redirect(
        url_for("index")
    )


@app.post("/pantry/<path:item_name>/delete")
@login_required
def pantry_item_delete(item_name):
    if not delete_pantry_item(
        item_name
    ):
        return (
            "Pantry item not found",
            404,
        )

    audit_event(
        "pantry_item_deleted",
        item_name,
    )

    flash(
        f"Removed pantry item: {item_name}."
    )

    return redirect(
        url_for("index")
    )


@app.post("/instalment/<int:index>/update")
@login_required
def instalment_update(index):
    def decimal_field(name):
        value = request.form.get(
            name,
            "",
        ).strip()

        if not value:
            return None

        return round(
            float(value),
            2,
        )

    def integer_field(name):
        value = request.form.get(
            name,
            "",
        ).strip()

        if not value:
            return None

        return max(
            0,
            int(value),
        )

    try:
        amount = decimal_field(
            "amount"
        )
        total_price = decimal_field(
            "total_price"
        )
        paid_to_date = decimal_field(
            "paid_to_date"
        )
        remaining_balance = decimal_field(
            "remaining_balance"
        )
        payments_remaining = integer_field(
            "payments_remaining"
        )
    except ValueError:
        flash(
            "Invalid instalment value."
        )
        return redirect(
            url_for("index")
        )

    next_payment = request.form.get(
        "next_payment",
        "",
    ).strip()

    with edit_json(
        SUBSCRIPTIONS_FILE,
        {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        },
    ) as data:
        instalments = data.setdefault(
            "instalments",
            [],
        )

        if (
            index < 0
            or index >= len(instalments)
        ):
            return (
                "Instalment not found",
                404,
            )

        item = instalments[index]

        item["name"] = request.form.get(
            "name",
            item.get(
                "name",
                "",
            ),
        ).strip()

        item["amount"] = amount
        item["total_price"] = total_price
        item["paid_to_date"] = paid_to_date
        item[
            "remaining_balance"
        ] = remaining_balance
        item[
            "payments_remaining"
        ] = payments_remaining
        item["next_payment"] = (
            next_payment
            or None
        )

        item_name = item[
            "name"
        ]

    audit_event(
        "instalment_updated",
        item_name,
    )

    flash(
        f"{item_name} updated."
    )

    return redirect(
        url_for("index")
    )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        if check_password_hash(
                load_password_hash(),
                request.form.get(
                    "password",
                    "",
                ),
        ):
            session.clear(); session["authenticated"] = True; session.permanent = True
            return redirect(url_for("index"))
        flash("Incorrect password.")
    return render_template("login.html")

@app.post("/logout")
@login_required
def logout(): session.clear(); return redirect(url_for("login"))

@app.get("/")
@login_required
def index():
    global _database_backup_checked

    if not _database_backup_checked:
        try:
            backup_database_if_due()
        except Exception as error:
            audit_event(
                "database_backup_failed",
                str(error),
            )
        finally:
            _database_backup_checked = True

    settings = load_receipt_settings()
    routines = load_routines()
    subscriptions = load_subscriptions()
    printer_settings = load_printer_settings()
    freezer = load_freezer()
    pantry = load_pantry()
    file_status = data_file_status()

    today_meal = None
    today_meal_error = None

    try:
        today_meal = get_meal()
    except Exception as error:
        today_meal_error = str(error)

    for item in routines:
        due = next_due_date(item)
        item["next_due_display"] = (
            due.strftime("%a %d %b").upper()
            if due
            else "NOT SET"
        )

    (
        food_shop_items,
        food_shop_error,
    ) = load_food_shop_items()

    return render_template(
        "index.html",
        settings=settings,
        routines=routines,
        weekdays=WEEKDAYS,
        subscriptions=subscriptions,
        food_shop_items=food_shop_items,
        food_shop_error=food_shop_error,
        printer_settings=printer_settings,
        printer_connection_label=printer_connection_label(
            printer_settings
        ),
        freezer=freezer,
        pantry=pantry,
        file_status=file_status,
        today_meal=today_meal,
        today_meal_error=today_meal_error,
    )

def _checked(name): return request.form.get(name) == "on"

@app.post("/save")
@login_required
def save():
    def mutate(settings):
        features = settings.setdefault(
            "features",
            {},
        )

        for name in (
            "calendar",
            "deliveries",
            "weather",
            "national_news",
            "local_news",
            "villa",
            "villa_trains",
        ):
            features[name] = _checked(
                name
            )

        one_shot = settings.setdefault(
            "one_shot",
            {},
        )

        for name in (
            "finance_check",
            "food_shop",
            "shopping_list",
        ):
            if _checked(
                name
            ):
                one_shot[name] = True

        display = settings.setdefault(
            "display",
            {},
        )

        detail = request.form.get(
            "weather_detail",
            "auto",
        )

        display[
            "weather_detail"
        ] = (
            detail
            if detail in {
                "auto",
                "compact",
                "full",
            }
            else "auto"
        )

        try:
            display["news_count"] = max(
                1,
                min(
                    10,
                    int(
                        request.form.get(
                            "news_count",
                            3,
                        )
                    ),
                ),
            )
        except ValueError:
            display[
                "news_count"
            ] = 3

        try:
            display[
                "earlier_journeys"
            ] = max(
                0,
                min(
                    5,
                    int(
                        request.form.get(
                            "earlier_journeys",
                            3,
                        )
                    ),
                ),
            )
        except ValueError:
            display[
                "earlier_journeys"
            ] = 3

    update_state(
        "receipt_settings",
        load_receipt_settings(),
        mutate,
    )

    audit_event(
        "receipt_settings_updated"
    )

    flash(
        "Settings saved."
    )

    return redirect(
        url_for("index")
    )


@app.post("/one-shot/<name>/clear")
@login_required
def clear_one_shot(name):
    if name not in {
        "finance_check",
        "food_shop",
        "shopping_list",
    }:
        return (
            "Unknown request",
            404,
        )

    def mutate(settings):
        settings.setdefault(
            "one_shot",
            {},
        )[name] = False

    update_state(
        "receipt_settings",
        load_receipt_settings(),
        mutate,
    )

    audit_event(
        "one_shot_cleared",
        name,
    )

    return redirect(
        url_for("index")
    )


@app.post("/routine/add")
@login_required
def routine_add():
    name = request.form.get("name", "").strip(); kind = request.form.get("schedule_type", "")
    if not name or kind not in {"weekly", "interval"}: flash("Enter a valid routine."); return redirect(url_for("index"))
    try:
        interval = max(1, int(request.form.get("interval_days", 7))); before = max(0, int(request.form.get("show_days_before", 0)))
    except ValueError: flash("Invalid schedule number."); return redirect(url_for("index"))
    add_routine(name, kind, weekday=request.form.get("weekday", "monday") if kind == "weekly" else None,
                interval_days=interval if kind == "interval" else None, show_days_before=before)
    flash("Routine added."); return redirect(url_for("index"))

@app.post("/routine/<routine_id>/done")
@login_required
def routine_done(routine_id): mark_done(routine_id); return redirect(url_for("index"))
@app.post("/routine/<routine_id>/toggle")
@login_required
def routine_toggle(routine_id): set_enabled(routine_id, request.form.get("enabled") == "1"); return redirect(url_for("index"))
@app.post("/routine/<routine_id>/delete")
@login_required
def routine_delete(routine_id): delete_routine(routine_id); return redirect(url_for("index"))

def _run_receipt_job(
    app_path,
    project_root,
    lock_path,
):
    try:
        subprocess.run(
            [
                sys.executable,
                str(app_path),
            ],
            cwd=project_root,
            check=False,
        )

    finally:
        Path(
            lock_path
        ).unlink(
            missing_ok=True
        )


PRINT_PAGES = {
    "information": "Information (header, weather, news)",
    "actions": "Actions (calendar, to-do, food shop, deliveries, exercises)",
    "food": "Food / meal planner",
    "finance": "Finance",
}


def _tesco_search_url(item):
    return (
        "https://www.tesco.com/shop/en-GB/search"
        f"?query={quote_plus(str(item).strip())}"
    )


@app.get("/tesco/search")
@login_required
def tesco_search():
    item = request.args.get("item", "").strip()

    if not item:
        flash("Choose a food-shop item first.")
        return redirect(url_for("index"))

    return redirect(_tesco_search_url(item))


def _rotate_log(
    path,
    max_bytes=1_000_000,
    backups=3,
):
    path = Path(
        path
    )

    if (
        not path.exists()
        or path.stat().st_size
        < max_bytes
    ):
        return

    for index in range(
        backups,
        0,
        -1,
    ):
        source = (
            path
            if index == 1
            else path.with_name(
                path.name
                + f".{index - 1}"
            )
        )

        destination = path.with_name(
            path.name
            + f".{index}"
        )

        if source.exists():
            destination.unlink(
                missing_ok=True
            )
            source.replace(
                destination
            )


def _start_print_command(command_args):
    lock = (
        PROJECT_ROOT
        / "data"
        / ".print_now.lock"
    )

    log_file = (
        PROJECT_ROOT
        / "logs"
        / "web_print.log"
    )

    lock.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if lock.exists():
        try:
            pid = int(
                lock.read_text(
                    encoding="utf-8"
                ).strip()
            )
            os.kill(pid, 0)
            return False, "A receipt job is already running."
        except (
            ValueError,
            ProcessLookupError,
            PermissionError,
            OSError,
        ):
            lock.unlink(
                missing_ok=True
            )

    try:
        _rotate_log(
            log_file
        )

        log_handle = open(
            log_file,
            "a",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            *command_args,
        ]

        shell_command = (
            " ".join(
                shlex.quote(part)
                for part in command
            )
            + "; status=$?; "
            + f"rm -f {shlex.quote(str(lock))}; "
            + "exit $status"
        )

        process = subprocess.Popen(
            [
                "/bin/sh",
                "-c",
                shell_command,
            ],
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        log_handle.close()

        lock.write_text(
            str(process.pid),
            encoding="utf-8",
        )

    except Exception as error:
        lock.unlink(
            missing_ok=True
        )
        print(
            "Web print error:",
            repr(error),
        )
        return False, "Could not start receipt."

    audit_event(
        "print_started",
        " ".join(
            command_args
        )
        or "full receipt",
    )

    return True, None


@app.post("/print-page")
@login_required
def print_page():
    page = request.form.get(
        "page",
        "",
    ).strip().lower()

    if page not in PRINT_PAGES:
        return ("Unknown receipt page", 400)

    started, error = _start_print_command(
        ["--only", page]
    )

    if not started:
        flash(error)
        return redirect(url_for("index"))

    flash(
        f"{PRINT_PAGES[page]} receipt started."
    )

    return redirect(
        url_for("index")
    )


@app.post("/print-now")
@login_required
def print_now():
    lock = (
        PROJECT_ROOT
        / "data"
        / ".print_now.lock"
    )

    log_file = (
        PROJECT_ROOT
        / "logs"
        / "web_print.log"
    )

    lock.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ----------------------------------------
    # Check existing lock
    # ----------------------------------------

    if lock.exists():
        try:
            pid = int(
                lock.read_text(
                    encoding="utf-8"
                ).strip()
            )

            # Check whether that process
            # genuinely still exists.
            os.kill(pid, 0)

            flash(
                "A receipt job is already running."
            )

            return redirect(
                url_for("index")
            )

        except (
            ValueError,
            ProcessLookupError,
            PermissionError,
            OSError,
        ):
            # Invalid/stale lock.
            lock.unlink(
                missing_ok=True
            )

    started, error = _start_print_command([])

    if not started:
        flash(error)
        return redirect(
            url_for("index")
        )

    flash(
        "Receipt started."
    )

    return redirect(
        url_for("index")
    )

if __name__ == "__main__": app.run(host="0.0.0.0", port=5000, debug=False)
