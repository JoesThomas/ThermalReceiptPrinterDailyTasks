from __future__ import annotations
import os, subprocess, sys
import shlex
import json
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from receipt_settings import load_receipt_settings, save_receipt_settings
from routines import WEEKDAYS, add_routine, delete_routine, load_routines, mark_done, next_due_date, set_enabled

app = Flask(__name__)

import json

SUBSCRIPTIONS_FILE = (
    PROJECT_ROOT / "data" / "subscriptions.json"
)


def load_subscriptions():
    if not SUBSCRIPTIONS_FILE.exists():
        return {
            "monthly": [],
            "yearly": [],
            "instalments": [],
        }

    with SUBSCRIPTIONS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    data.setdefault("monthly", [])
    data.setdefault("yearly", [])
    data.setdefault("instalments", [])

    return data


def save_subscriptions(data):
    """
    Save subscription and instalment changes
    made through Receipt Control.
    """
    SUBSCRIPTIONS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = SUBSCRIPTIONS_FILE.with_suffix(
        ".json.tmp"
    )

    with temp_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )

        file.write("\n")

    temp_file.replace(
        SUBSCRIPTIONS_FILE
    )


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


app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
if os.environ.get("RECEIPT_WEB_SECURE_COOKIE") == "1": app.config["SESSION_COOKIE_SECURE"] = True

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"): return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.post("/instalment/<int:index>/update")
@login_required
def instalment_update(index):
    data = load_subscriptions()
    instalments = data.get("instalments", [])

    if index < 0 or index >= len(instalments):
        return ("Instalment not found", 404)

    item = instalments[index]

    item["name"] = request.form.get(
        "name",
        item.get("name", ""),
    ).strip()

    def decimal_field(name):
        value = request.form.get(name, "").strip()

        if not value:
            return None

        return round(float(value), 2)

    def integer_field(name):
        value = request.form.get(name, "").strip()

        if not value:
            return None

        return max(0, int(value))

    try:
        item["amount"] = decimal_field("amount")
        item["total_price"] = decimal_field(
            "total_price"
        )
        item["paid_to_date"] = decimal_field(
            "paid_to_date"
        )
        item["remaining_balance"] = decimal_field(
            "remaining_balance"
        )
        item["payments_remaining"] = integer_field(
            "payments_remaining"
        )

    except ValueError:
        flash("Invalid instalment value.")
        return redirect(url_for("index"))

    next_payment = request.form.get(
        "next_payment",
        "",
    ).strip()

    item["next_payment"] = (
        next_payment or None
    )

    save_subscriptions(data)

    flash(
        f"{item['name']} updated."
    )

    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
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
    settings = load_receipt_settings()
    routines = load_routines()
    subscriptions = load_subscriptions()

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
    )

def _checked(name): return request.form.get(name) == "on"

@app.post("/save")
@login_required
def save():
    settings = load_receipt_settings()
    for name in ("calendar", "deliveries", "weather", "national_news", "local_news", "villa", "villa_trains"):
        settings["features"][name] = _checked(name)
    for name in ("finance_check", "food_shop", "shopping_list"):
        if _checked(name): settings["one_shot"][name] = True
    detail = request.form.get("weather_detail", "auto")
    settings["display"]["weather_detail"] = detail if detail in {"auto", "compact", "full"} else "auto"
    try: settings["display"]["news_count"] = max(1, min(10, int(request.form.get("news_count", 3))))
    except ValueError: settings["display"]["news_count"] = 3
    try: settings["display"]["earlier_journeys"] = max(0, min(5, int(request.form.get("earlier_journeys", 3))))
    except ValueError: settings["display"]["earlier_journeys"] = 3
    save_receipt_settings(settings); flash("Settings saved."); return redirect(url_for("index"))

@app.post("/one-shot/<name>/clear")
@login_required
def clear_one_shot(name):
    if name not in {"finance_check", "food_shop", "shopping_list"}: return ("Unknown request", 404)
    settings = load_receipt_settings(); settings["one_shot"][name] = False; save_receipt_settings(settings)
    return redirect(url_for("index"))

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
        "https://www.tesco.com/groceries/en-GB/search"
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
