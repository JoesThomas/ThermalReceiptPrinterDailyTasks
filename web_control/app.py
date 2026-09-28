from __future__ import annotations
import os, subprocess, sys
import json
import math
from datetime import timedelta, datetime
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from receipt_settings import load_receipt_settings, save_receipt_settings
from receipt.location_settings import validate_location
from routines import WEEKDAYS, add_routine, delete_routine, load_routines, mark_done, next_due_date, set_enabled
from web_control.charts import finance_charts, instalment_progress
from web_control.payments import external_payments, monthly_payments
from web_control.live_data import (food_shop_override, save_food_shop, tesco_progress,
                                   mark_tesco_item, meal_confirmation, confirm_meal,
                                   clear_meal_confirmation, map_embed_url, map_link_url)

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
    local_items = food_shop_override()
    if local_items is not None:
        return local_items, None
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
    for item in subscriptions.get("instalments", []):
        if isinstance(item, dict):
            item["progress"] = instalment_progress(item)

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
        print_status=load_print_status(),
        settings=settings,
        routines=routines,
        weekdays=WEEKDAYS,
        subscriptions=subscriptions,
        food_shop_items=food_shop_items,
        food_shop_text="\n".join(food_shop_items),
        food_shop_error=food_shop_error,
        food_shop_is_local=food_shop_override() is not None,
    )

def _checked(name): return request.form.get(name) == "on"

@app.post("/save")
@login_required
def save():
    settings = load_receipt_settings()
    if any(key in request.form for key in ("name", "region", "latitude", "longitude",
                                           "local_news_label", "local_news_feed")):
        try:
            settings["location"] = validate_location(request.form)
        except ValueError as error:
            flash(str(error))
            return redirect(url_for("index"))
    for name in ("calendar", "deliveries", "weather", "national_news", "local_news", "sport_news", "villa", "villa_trains"):
        settings["features"][name] = _checked(name)
    for name in ("finance_check", "food_shop", "shopping_list"):
        if _checked(name): settings["one_shot"][name] = True
    detail = request.form.get("weather_detail", "auto")
    settings["display"]["weather_detail"] = detail if detail in {"auto", "compact", "full"} else "auto"
    try: settings["display"]["news_count"] = max(1, min(10, int(request.form.get("news_count", 3))))
    except ValueError: settings["display"]["news_count"] = 3
    try: settings["display"]["sport_count"] = max(1, min(5, int(request.form.get("sport_count", 3))))
    except ValueError: settings["display"]["sport_count"] = 3
    if "therapy_payee" in request.form:
        settings["therapy_payment"]["payee"] = request.form["therapy_payee"].strip()[:80]
        provider = request.form.get("therapy_provider", "MONZO").upper()
        settings["therapy_payment"]["provider"] = provider if provider in {"MONZO", "HSBC"} else "MONZO"
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


def _local_today():
    return datetime.now(ZoneInfo("Europe/London")).date()


def _recipe_items():
    from meals import legacy_planner as meals
    return meals, [recipe for recipe in meals.recipes() if recipe.get("name")]


@app.get("/meals")
@login_required
def meals_page():
    meals, recipes = _recipe_items()
    today = _local_today()
    try:
        planned = meals.get_meal(today)
        problem = None
    except (RuntimeError, ValueError, OSError) as error:
        planned, problem = None, str(error)
    return render_template("meals.html", recipes=recipes, planned=planned,
                           confirmed=meal_confirmation(today), today=today, error=problem)


@app.post("/meals/plan")
@login_required
def change_today_meal():
    meals, recipes = _recipe_items()
    today = _local_today()
    selected = next((item for item in recipes if item["name"] == request.form.get("recipe")), None)
    if selected is None:
        return ("Choose a recipe from the list", 400)
    plan = meals.load_plan_for(today) or meals.generate_week(meals.current_week_sunday(today))
    if not any(item.get("date") == today.isoformat() for item in plan.get("meals", [])):
        return ("Today's meal is not in the plan", 400)
    plan["meals"] = [({"date": today.isoformat(), "kind": "recipe", "recipe": selected}
                     if item.get("date") == today.isoformat() else item)
                     for item in plan["meals"]]
    plan["shopping"] = meals.build_shopping_list(plan)
    plan["prep"] = meals.build_sunday_prep(plan)
    plan["estimated_cost"] = meals.estimate_week_cost(plan)
    meals._save(meals.plan_path(meals.current_week_sunday(today)), plan)
    flash("Today's recipe and meal shopping list updated.")
    return redirect(url_for("meals_page"))


@app.post("/meals/eaten")
@login_required
def meal_eaten():
    _, recipes = _recipe_items()
    name = request.form.get("recipe", "")
    try:
        confirm_meal(_local_today(), name, {recipe["name"] for recipe in recipes})
    except ValueError:
        return ("Choose a recipe from the list", 400)
    flash("Meal confirmed as eaten.")
    return redirect(url_for("meals_page"))


@app.post("/meals/eaten/clear")
@login_required
def meal_eaten_clear():
    clear_meal_confirmation(_local_today())
    flash("Meal confirmation removed.")
    return redirect(url_for("meals_page"))


@app.get("/calendar-map")
@login_required
def calendar_map():
    events, error = [], None
    try:
        private = json.loads(PROJECT_PASSWORDS_FILE.read_text(encoding="utf-8"))
        ical_url = private.get("calendar", {}).get("ical_url")
        if not ical_url:
            raise ValueError("Calendar iCal URL is not configured.")
        from services.live_pipeline import get_calendar_events
        events = get_calendar_events(ical_url, days_ahead=7)
        for event in events:
            event["map_url"] = map_embed_url(event.get("location", ""))
            event["map_link"] = map_link_url(event.get("location", ""))
    except Exception:
        app.logger.exception("Calendar map unavailable")
        error = "Calendar events are unavailable. Check your iCal connection."
    return render_template("calendar_map.html", events=events, error=error)


@app.post("/food-shop/save")
@login_required
def food_shop_save():
    try:
        save_food_shop(request.form.get("items", ""))
    except ValueError as error:
        flash(str(error))
    else:
        flash("Shopping items saved for the next receipt and Tesco review.")
    return redirect(url_for("index") + "#food-shop")


@app.post("/food-shop/reset")
@login_required
def food_shop_reset():
    from web_control.live_data import FOOD_SHOP_FILE
    FOOD_SHOP_FILE.unlink(missing_ok=True)
    flash("Using the Google Doc shopping list again.")
    return redirect(url_for("index") + "#food-shop")


def _tesco_list():
    items, error = load_food_shop_items()
    from meals import legacy_planner as meals
    plan = meals.load_plan_for(_local_today())
    if plan is None:
        try:
            meals.get_meal(_local_today())
            plan = meals.load_plan_for(_local_today())
        except (RuntimeError, ValueError, OSError):
            plan = None
    meal_items = [item for group in plan.get("shopping", {}).values() for item in group] if plan else []
    return list(dict.fromkeys(items + meal_items)), error


@app.get("/tesco")
@login_required
def tesco_list():
    items, error = _tesco_list()
    return render_template("tesco.html", items=items, error=error,
                           progress=tesco_progress(items))


@app.post("/tesco/progress")
@login_required
def tesco_mark():
    items, _ = _tesco_list()
    try:
        mark_tesco_item(request.form.get("item", ""), items,
                        request.form.get("added") == "1")
    except ValueError:
        return ("Item no longer exists in the shopping list", 400)
    return redirect(url_for("tesco_list"))


def _monthly_entry():
    name = request.form.get("name", "").strip()
    if not name or len(name) > 90:
        raise ValueError("Enter a name up to 90 characters.")
    amount = round(float(request.form.get("amount", "")), 2)
    if not math.isfinite(amount) or amount <= 0 or amount > 100000:
        raise ValueError("Enter a positive payment amount.")
    match = [term.strip() for term in request.form.get("match", "").split(",") if term.strip()]
    if len(match) > 6 or any(len(term) > 90 for term in match):
        raise ValueError("Use up to six short bank matching terms.")
    return {"name": name, "amount": amount, "match": match,
            "category": request.form.get("category") if request.form.get("category") in
            {"bill", "subscription", "savings", "repayment"} else "subscription"}


@app.post("/commitment/add")
@login_required
def commitment_add():
    try:
        item = _monthly_entry()
    except (ValueError, OverflowError):
        flash("Enter a valid name, amount and matching terms.")
        return redirect(url_for("index") + "#commitments")
    data = load_subscriptions()
    data["monthly"].append(item)
    save_subscriptions(data)
    flash("Monthly commitment added.")
    return redirect(url_for("index") + "#commitments")


@app.post("/commitment/<int:index>/update")
@login_required
def commitment_update(index):
    data = load_subscriptions()
    if index >= len(data["monthly"]):
        return ("Commitment not found", 404)
    try:
        item = _monthly_entry()
    except (ValueError, OverflowError):
        flash("Enter a valid name, amount and matching terms.")
        return redirect(url_for("index") + "#commitments")
    data["monthly"][index].update(item)
    save_subscriptions(data)
    flash("Monthly commitment updated.")
    return redirect(url_for("index") + "#commitments")


@app.post("/commitment/<int:index>/delete")
@login_required
def commitment_delete(index):
    data = load_subscriptions()
    if index >= len(data["monthly"]):
        return ("Commitment not found", 404)
    data["monthly"].pop(index)
    save_subscriptions(data)
    flash("Monthly commitment removed.")
    return redirect(url_for("index") + "#commitments")


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

        process = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "web_control" / "print_job.py"),
             *command_args],
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


def load_print_status():
    path = PROJECT_ROOT / "data" / "web_print_status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        if status.get("state") not in {"running", "completed", "failed"}:
            return None
        if status["state"] == "running":
            lock = PROJECT_ROOT / "data" / ".print_now.lock"
            try:
                os.kill(int(lock.read_text(encoding="utf-8").strip()), 0)
            except (OSError, ValueError):
                status["state"] = "interrupted"
        return status
    except (OSError, ValueError, KeyError, TypeError):
        return None


@app.get("/preview")
@login_required
def preview():
    from receipt.capture import PAGE_NAMES, LIVE_PREVIEW_FILE, load_capture, receipt_blocks
    from receipt.local_time import uk_receipt_time
    from receipt.visual_sample import example_pages
    page = request.args.get("page", "all")
    if page not in {"all", *PRINT_PAGES}:
        return ("Unknown receipt page", 400)
    source = request.args.get("source", "live")
    if source not in {"live", "printed"}:
        return ("Unknown receipt source", 400)
    live_capture = load_capture(LIVE_PREVIEW_FILE)
    printed_capture = load_capture()
    capture = (live_capture if source == "live" else printed_capture) or {"pages": {}, "page_times": {}}
    examples = example_pages(_local_today())
    selected = PAGE_NAMES if page == "all" else (page,)
    pages = [{"name": name, "text": capture["pages"].get(name) or examples[name],
              "blocks": receipt_blocks(capture["pages"].get(name) or examples[name],
                                       capture.get("page_images", {}).get(name, [])),
              "captured_at": capture.get("page_times", {}).get(name),
              "captured_local": uk_receipt_time(capture.get("page_times", {}).get(name)),
              "sample": not bool(capture["pages"].get(name))}
             for name in selected]
    return render_template("preview.html", pages=pages, page=page, source=source,
                           preview_status=load_live_preview_status(),
                           has_live=bool(live_capture), has_printed=bool(printed_capture))


def load_live_preview_status():
    path = PROJECT_ROOT / "data" / "live_preview_status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        if status.get("state") not in {"running", "completed", "failed"}:
            return None
        if status["state"] == "running":
            lock = PROJECT_ROOT / "data" / ".live_preview.lock"
            try:
                os.kill(int(lock.read_text(encoding="utf-8").strip()), 0)
            except (OSError, ValueError):
                status["state"] = "interrupted"
        return status
    except (OSError, ValueError, KeyError, TypeError):
        return None


@app.get("/preview/status")
@login_required
def live_preview_status_api():
    return jsonify(load_live_preview_status() or {"state": "idle"})


@app.post("/preview/generate")
@login_required
def generate_live_preview():
    lock = PROJECT_ROOT / "data" / ".live_preview.lock"
    log_file = PROJECT_ROOT / "logs" / "web_preview.log"
    lock.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            os.kill(int(lock.read_text(encoding="utf-8").strip()), 0)
            flash("A live preview is already being generated.")
            return redirect(url_for("preview", source="live"))
        except (OSError, ValueError):
            lock.unlink(missing_ok=True)
    try:
        from web_control.preview_job import save_status
        save_status("running")
        with log_file.open("a", encoding="utf-8") as log_handle:
            args = ["--finance"] if request.form.get("include_finance") == "on" else []
            process = subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "web_control" / "preview_job.py"), *args],
                cwd=PROJECT_ROOT, stdout=log_handle, stderr=subprocess.STDOUT,
                start_new_session=True)
        lock.write_text(str(process.pid), encoding="utf-8")
        flash("Fetching current receipt data. This may take a few minutes.")
    except Exception:
        from web_control.preview_job import save_status
        save_status("failed")
        app.logger.exception("Could not start live preview")
        lock.unlink(missing_ok=True)
        flash("Could not start live preview. Please try again.")
    return redirect(url_for("preview", source="live"))


@app.get("/finance-review")
@login_required
def finance_review():
    from finance.commitments import matching_repayment_transaction
    from services.live_pipeline import (build_subscription_status,
                                        get_regular_finance_data,
                                        matching_subscription_transaction)
    today = datetime.now(ZoneInfo("Europe/London")).date()
    try:
        transactions = get_regular_finance_data()[0]
        status = build_subscription_status(transactions, today=today)
        used = set()
        rows = []
        for item in status["monthly"]:
            index = matching_subscription_transaction(item, transactions, today, used)
            method = "Merchant and amount"
            if index is None and item.get("category") == "repayment":
                index = matching_repayment_transaction(item, transactions, today, used)
                method = "Payment date and amount"
            if index is not None:
                used.add(index)
            tx = transactions[index] if index is not None else None
            rows.append({"item": item, "transaction": tx, "method": method})
        payments = external_payments(transactions)
        charts = finance_charts(payments, status["monthly"], today)
        month = monthly_payments(transactions, today)
        return render_template("finance_review.html", rows=rows, charts=charts,
                               month=month,
                               checked_at=today, error=None)
    except Exception:
        app.logger.exception("Could not load finance review")
        return render_template("finance_review.html", rows=[], checked_at=today,
                               error="Bank transactions are unavailable. Try again later."), 503


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
