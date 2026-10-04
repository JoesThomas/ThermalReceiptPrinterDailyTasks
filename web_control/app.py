from __future__ import annotations
import os, subprocess, sys
import json
import math
import secrets
import time
from hmac import compare_digest
from threading import Lock
from datetime import timedelta, datetime, date
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from receipt_settings import load_receipt_settings, save_receipt_settings
from receipt.location_settings import validate_location
from routines import WEEKDAYS, add_routine, delete_routine, load_routines, mark_done, next_due_date, set_enabled
from web_control.charts import finance_charts, instalment_progress
from web_control.payments import (cash_flow_review, external_payments,
                                  incoming_review, monthly_payments)
from web_control.live_data import (food_shop_override, save_food_shop, tesco_progress,
                                   mark_tesco_item, meal_confirmation, confirm_meal,
                                   clear_meal_confirmation, map_embed_url, map_link_url)
from web_control.to_buy import load_to_buy, save_to_buy
from web_control.future_tasks import load_tasks, update_task
from web_control.job_process import watch_job

app = Flask(__name__)

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
    from storage import write_json
    write_json(SUBSCRIPTIONS_FILE, data)


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
    SESSION_COOKIE_SECURE=os.environ.get("RECEIPT_WEB_SECURE_COOKIE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=1024 * 1024,
)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.after_request
def private_response_headers(response):
    if session.get('authenticated') or request.endpoint == 'login':
        response.headers['Cache-Control'] = 'no-store'
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    return response


@app.before_request
def require_csrf():
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not compare_digest(expected, supplied):
            abort(403)


# This is a per-process limit; use a shared store if running multiple workers.
_login_attempts = {}
_login_attempts_lock = Lock()
_LOGIN_WINDOW = 15 * 60
_LOGIN_MAX_ATTEMPTS = 5


def _login_limited(address, failed=False):
    now = time.monotonic()
    with _login_attempts_lock:
        attempts = [when for when in _login_attempts.get(address, ())
                    if now - when < _LOGIN_WINDOW]
        if failed:
            attempts.append(now)
        if attempts:
            _login_attempts[address] = attempts
        else:
            _login_attempts.pop(address, None)
        return len(attempts) >= _LOGIN_MAX_ATTEMPTS

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

        amount = round(float(value), 2)
        if not math.isfinite(amount) or amount < 0 or amount > 1_000_000_000:
            raise ValueError('Invalid amount')
        return amount

    def integer_field(name):
        value = request.form.get(name, "").strip()

        if not value:
            return None

        number = int(value)
        if not 0 <= number <= 1_000_000:
            raise ValueError('Invalid payment count')
        return number

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
        return redirect(url_for("index", view="accounts"))

    next_payment = request.form.get(
        "next_payment",
        "",
    ).strip()

    if next_payment:
        try:
            date.fromisoformat(next_payment)
        except ValueError:
            flash("Use a valid next payment date.")
            return redirect(url_for("index", view="accounts"))
    item["next_payment"] = next_payment or None

    save_subscriptions(data)

    flash(
        f"{item['name']} updated."
    )

    return redirect(url_for("index", view="accounts"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        address = request.remote_addr or "unknown"
        if _login_limited(address):
            return ("Too many sign-in attempts. Try again in 15 minutes.", 429)
        if check_password_hash(
                load_password_hash(),
                request.form.get(
                    "password",
                    "",
                ),
        ):
            with _login_attempts_lock:
                _login_attempts.pop(address, None)
            session.clear(); session["authenticated"] = True; session.permanent = True
            return redirect(url_for("index"))
        _login_limited(address, failed=True)
        flash("Incorrect password.")
    return render_template("login.html")

@app.post("/logout")
@login_required
def logout(): session.clear(); return redirect(url_for("login"))

@app.get("/")
@login_required
def index():
    active_view = request.args.get("view", "dashboard")
    if active_view not in {"dashboard", "receipt", "tasks", "accounts", "settings"}:
        active_view = "dashboard"
    from web_control.scheduled_print import next_print_time
    status = load_print_status()
    last_print_local = None
    if status and status.get("updated_at"):
        try:
            stamp = datetime.fromisoformat(status["updated_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=ZoneInfo("UTC"))
            last_print_local = stamp.astimezone(ZoneInfo("Europe/London")).strftime("%d %b, %H:%M %Z")
        except (ValueError, TypeError):
            pass
    settings = load_receipt_settings()
    scheduled_at = next_print_time(datetime.now(ZoneInfo("Europe/London")), settings)
    from services.local_gigs import options as gig_options
    settings["features"]["local_gigs"] = gig_options()["enabled"]
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

    from web_control.today_summary import dashboard
    today_view = dashboard() if active_view == "dashboard" else {}
    return render_template(
        "index.html",
        print_status=status,
        today_view=today_view,
        active_view=active_view, scheduled_at=scheduled_at, last_print_local=last_print_local,
        settings=settings,
        routines=routines,
        weekdays=WEEKDAYS,
        subscriptions=subscriptions,
        food_shop_items=food_shop_items,
        food_shop_text="\n".join(food_shop_items),
        food_shop_error=food_shop_error,
        food_shop_is_local=food_shop_override() is not None,
        to_buy_items=load_to_buy(),
        future_tasks=load_tasks(),
    )

def _checked(name): return request.form.get(name) == "on"

@app.post('/settings/print-schedule')
@login_required
def save_print_schedule():
    import re
    value = request.form.get('time', '')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        flash('Choose a valid daily print time.')
        return redirect(url_for('index', view='settings'))
    settings = load_receipt_settings()
    settings['print_schedule'] = {'enabled': _checked('enabled'), 'time': value}
    save_receipt_settings(settings)
    flash('Daily print schedule saved. Changes take effect within 30 seconds.')
    return redirect(url_for('index', view='settings'))

@app.post('/settings/receipt-layout')
@login_required
def save_receipt_layout():
    from receipt.layout import validate as validate_layout
    try:
        layout = validate_layout({'order': [request.form.get(f'page_{n}', '') for n in range(4)],
                                  'detail': request.form.get('detail', 'detailed')})
        settings = load_receipt_settings()
        settings['layout'] = layout
        save_receipt_settings(settings)
        flash('Receipt layout saved. The current order remains unless you choose a different order.')
    except ValueError as error:
        flash(str(error))
    return redirect(url_for('index', view='settings'))

@app.post("/save")
@login_required
def save():
    return_view = request.form.get("return_view", "receipt")
    if return_view not in {"receipt", "settings"}:
        return_view = "receipt"
    settings = load_receipt_settings()
    if any(key in request.form for key in ("name", "region", "latitude", "longitude",
                                           "local_news_label", "local_news_feed")):
        try:
            settings["location"] = validate_location(request.form)
        except ValueError as error:
            flash(str(error))
            return redirect(url_for("index", view=return_view))
    for name in ("calendar", "deliveries", "weather", "national_news", "local_news", "sport_news", "villa", "villa_trains"):
        settings["features"][name] = _checked(name)
    from services.local_gigs import options as gig_options, save_options as save_gig_options
    current_gigs = gig_options()
    save_gig_options(current_gigs["radius_km"],current_gigs["receipt_limit"],_checked("local_gigs"))
    for name in ("finance_check", "food_shop", "shopping_list", "to_buy", "future_tasks"):
        if _checked(name): settings["one_shot"][name] = True
    # Unlike existing requests, unticking To buy cancels its pending print.
    settings["one_shot"]["to_buy"] = _checked("to_buy")
    settings["one_shot"]["future_tasks"] = _checked("future_tasks")
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
    if "salary_payee" in request.form:
        settings["finance"]["salary_payee"] = request.form["salary_payee"].strip()[:80]
    save_receipt_settings(settings); flash("Settings saved."); return redirect(url_for("index", view=return_view))

@app.post("/one-shot/<name>/clear")
@login_required
def clear_one_shot(name):
    if name not in {"finance_check", "food_shop", "shopping_list", "to_buy", "future_tasks"}: return ("Unknown request", 404)
    settings = load_receipt_settings(); settings["one_shot"][name] = False; save_receipt_settings(settings)
    return redirect(url_for("index", view="receipt"))

@app.post("/routine/add")
@login_required
def routine_add():
    name = request.form.get("name", "").strip(); kind = request.form.get("schedule_type", "")
    if not name or kind not in {"weekly", "interval"}: flash("Enter a valid routine."); return redirect(url_for("index", view="tasks"))
    try:
        interval = max(1, int(request.form.get("interval_days", 7))); before = max(0, int(request.form.get("show_days_before", 0)))
    except ValueError: flash("Invalid schedule number."); return redirect(url_for("index", view="tasks"))
    try:
        add_routine(name, kind, weekday=request.form.get("weekday", "monday") if kind == "weekly" else None,
                    interval_days=interval if kind == "interval" else None, show_days_before=before)
    except ValueError as error:
        flash(str(error))
        return redirect(url_for('index', view='tasks'))
    flash("Routine added."); return redirect(url_for("index", view="tasks"))

@app.post("/routine/<routine_id>/done")
@login_required
def routine_done(routine_id): mark_done(routine_id); return redirect(url_for("index", view="tasks"))
@app.post("/routine/<routine_id>/toggle")
@login_required
def routine_toggle(routine_id): set_enabled(routine_id, request.form.get("enabled") == "1"); return redirect(url_for("index", view="tasks"))
@app.post("/routine/<routine_id>/delete")
@login_required
def routine_delete(routine_id): delete_routine(routine_id); return redirect(url_for("index", view="tasks"))

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
    return redirect(url_for("quick_actions" if request.form.get("return_quick") == "1" else "meals_page"))


@app.post("/meals/eaten/clear")
@login_required
def meal_eaten_clear():
    clear_meal_confirmation(_local_today())
    flash("Meal confirmation removed.")
    return redirect(url_for("quick_actions" if request.form.get("return_quick") == "1" else "meals_page"))


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
        from web_control.today_summary import save_calendar
        save_calendar(events)
        for event in events:
            event["map_url"] = map_embed_url(event.get("location", ""))
            event["map_link"] = map_link_url(event.get("location", ""))
    except Exception:
        app.logger.exception("Calendar map unavailable")
        error = "Calendar events are unavailable. Check your iCal connection."
    from services.source_cache import timings
    calendar_source = next((row for row in timings() if row["name"] == "Calendar"), {})
    from receipt.local_time import uk_receipt_time
    return render_template("calendar_map.html", events=events, error=error, calendar_source=calendar_source,
                           calendar_source_time=uk_receipt_time(calendar_source.get("source_checked_at")))


@app.post("/food-shop/save")
@login_required
def food_shop_save():
    try:
        save_food_shop(request.form.get("items", ""))
    except ValueError as error:
        flash(str(error))
    else:
        flash("Shopping items saved for the next receipt and Tesco review.")
    return redirect(url_for("index", view="tasks") + "#food-shop")


@app.post("/food-shop/reset")
@login_required
def food_shop_reset():
    from web_control.live_data import FOOD_SHOP_FILE
    FOOD_SHOP_FILE.unlink(missing_ok=True)
    flash("Using the Google Doc shopping list again.")
    return redirect(url_for("index", view="tasks") + "#food-shop")


@app.post("/to-buy/save")
@login_required
def to_buy_save():
    try:
        save_to_buy(request.form.get("items", ""))
    except ValueError as error:
        flash(str(error))
    else:
        flash("To buy list saved locally.")
    return redirect(url_for("index", view="tasks") + "#to-buy")


@app.post("/future-tasks/save")
@login_required
def future_tasks_save():
    try:
        action = request.form.get("action", "save")
        if action not in {"save", "toggle", "delete"}:
            raise ValueError("Unknown task action.")
        update_task(request.form.get("task_id") or None,
                    request.form.get("title", ""), request.form.get("next_step", ""), action)
    except (ValueError, OSError) as error:
        flash(str(error))
    else:
        flash("Future tasks saved locally.")
    return redirect(url_for("index", view="tasks") + "#future-tasks")


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
    end_date = request.form.get("end_date", "").strip()
    if end_date:
        end_date = date.fromisoformat(end_date).isoformat()
    due_day = request.form.get("due_day", "").strip()
    if due_day and not 1 <= int(due_day) <= 31:
        raise ValueError("Choose a payment day from 1 to 31.")
    return {"name": name, "amount": amount, "match": match,
            "end_date": end_date or None,
            "due_day": int(due_day) if due_day else None,
            "category": request.form.get("category") if request.form.get("category") in
            {"bill", "subscription", "savings", "repayment"} else "subscription"}


@app.post("/commitment/add")
@login_required
def commitment_add():
    try:
        item = _monthly_entry()
    except (ValueError, OverflowError):
        flash("Enter a valid name, amount and matching terms.")
        return redirect(url_for("index", view="accounts") + "#commitments")
    data = load_subscriptions()
    data["monthly"].append(item)
    save_subscriptions(data)
    flash("Monthly commitment added.")
    return redirect(url_for("index", view="accounts") + "#commitments")


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
        return redirect(url_for("index", view="accounts") + "#commitments")
    data["monthly"][index].update(item)
    save_subscriptions(data)
    flash("Monthly commitment updated.")
    return redirect(url_for("index", view="accounts") + "#commitments")


@app.post("/commitment/<int:index>/delete")
@login_required
def commitment_delete(index):
    data = load_subscriptions()
    if index >= len(data["monthly"]):
        return ("Commitment not found", 404)
    data["monthly"].pop(index)
    save_subscriptions(data)
    flash("Monthly commitment removed.")
    return redirect(url_for("index", view="accounts") + "#commitments")


def _annual_entry():
    name = request.form.get("name", "").strip()
    if not name or len(name) > 90:
        raise ValueError("Enter a short name.")
    amount = round(float(request.form.get("amount", "")), 2)
    if not math.isfinite(amount) or not 0 < amount <= 100000:
        raise ValueError("Enter a positive annual amount.")
    renewal_date = date.fromisoformat(request.form.get("renewal_date", ""))
    terms = [term.strip() for term in request.form.get("match", "").split(",") if term.strip()]
    if len(terms) > 6 or any(len(term) > 90 for term in terms):
        raise ValueError("Use up to six short bank matching terms.")
    return {"name": name, "amount": amount,
            "renewal_date": renewal_date.isoformat(), "match": terms,
            "category": "subscription"}


@app.post("/annual/add")
@login_required
def annual_add():
    try:
        item = _annual_entry()
    except (ValueError, OverflowError):
        flash("Enter a valid annual name, amount, renewal date and matching terms.")
        return redirect(url_for("index", view="accounts") + "#annual-subscriptions")
    data = load_subscriptions()
    data["yearly"].append(item)
    save_subscriptions(data)
    flash("Annual subscription added.")
    return redirect(url_for("index", view="accounts") + "#annual-subscriptions")


@app.post("/annual/<int:index>/update")
@login_required
def annual_update(index):
    data = load_subscriptions()
    if index >= len(data["yearly"]):
        return ("Annual subscription not found", 404)
    try:
        item = _annual_entry()
    except (ValueError, OverflowError):
        flash("Enter a valid annual name, amount, renewal date and matching terms.")
        return redirect(url_for("index", view="accounts") + "#annual-subscriptions")
    data["yearly"][index].update(item)
    save_subscriptions(data)
    flash("Annual subscription updated.")
    return redirect(url_for("index", view="accounts") + "#annual-subscriptions")


@app.post("/annual/<int:index>/delete")
@login_required
def annual_delete(index):
    data = load_subscriptions()
    if index >= len(data["yearly"]):
        return ("Annual subscription not found", 404)
    data["yearly"].pop(index)
    save_subscriptions(data)
    flash("Annual subscription removed.")
    return redirect(url_for("index", view="accounts") + "#annual-subscriptions")


PRINT_PAGES = {
    "information": "Information (header, weather, news, gigs)",
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
    with _print_start_lock:
        return _start_print_command_locked(command_args)


_print_start_lock = Lock()


def _job_active(path):
    try:
        pid = int(path.read_text(encoding='utf-8').strip())
        if not 0 < pid <= 2_147_483_647:
            return False
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ValueError, FileNotFoundError, ProcessLookupError):
        return False


def _start_print_command_locked(command_args):
    if _job_active(PROJECT_ROOT / 'data' / '.live_preview.lock'):
        return False, 'A live preview is running. Wait before starting a print.'
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

    if _job_active(lock):
        return False, "A receipt job is already running."
    lock.unlink(missing_ok=True)

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
        watch_job(process, lock)

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
        if not isinstance(status, dict) or status.get("state") not in {"running", "completed", "failed", "timed_out", "cancelled"}:
            return None
        if status["state"] == "running":
            lock = PROJECT_ROOT / "data" / ".print_now.lock"
            if not _job_active(lock):
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
    selected = (capture.get("page_order") or PAGE_NAMES) if page == "all" else (page,)
    pages = [{"name": name, "text": capture["pages"].get(name) or examples[name],
              "blocks": receipt_blocks(capture["pages"].get(name) or examples[name],
                                       capture.get("page_images", {}).get(name, [])),
              "captured_at": capture.get("page_times", {}).get(name),
              "captured_local": uk_receipt_time(capture.get("page_times", {}).get(name)),
              "sample": not bool(capture["pages"].get(name))}
             for name in selected]
    from receipt.quality import check
    quality_warnings = check(capture.get("pages", {}), capture.get("freshness", {}))
    return render_template("preview.html", quality_warnings=quality_warnings, freshness=[dict(name=name, status=value["status"], local=uk_receipt_time(value.get("source_checked_at") or value["checked_at"])) for name, value in capture.get("freshness", {}).items()], pages=pages, page=page, source=source,
                           preview_status=load_live_preview_status(),
                           has_live=bool(live_capture), has_printed=bool(printed_capture))


def load_live_preview_status():
    path = PROJECT_ROOT / "data" / "live_preview_status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(status, dict) or status.get("state") not in {"running", "completed", "failed", "timed_out", "cancelled"}:
            return None
        if status["state"] == "running":
            lock = PROJECT_ROOT / "data" / ".live_preview.lock"
            if not _job_active(lock):
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
    with _print_start_lock:
        return _generate_live_preview_locked()


def _generate_live_preview_locked():
    if request.form.get("page", "all") not in {"all", *PRINT_PAGES}:
        abort(400)
    if _job_active(PROJECT_ROOT / 'data' / '.print_now.lock'):
        flash('A print job is running. Wait before generating a preview.')
        return redirect(url_for('preview', source='live'))
    lock = PROJECT_ROOT / "data" / ".live_preview.lock"
    log_file = PROJECT_ROOT / "logs" / "web_preview.log"
    lock.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if _job_active(lock):
        flash("A live preview is already being generated.")
        return redirect(url_for("preview", source="live"))
    lock.unlink(missing_ok=True)
    try:
        from web_control.preview_job import save_status
        save_status("running")
        with log_file.open("a", encoding="utf-8") as log_handle:
            page = request.form.get('page', 'all')
            if page not in {'all', *PRINT_PAGES}:
                abort(400)
            args = ["--finance"] if request.form.get("include_finance") == "on" or page == 'finance' else []
            if page != 'all':
                args += ['--only', page]
            process = subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "web_control" / "preview_job.py"), *args],
                cwd=PROJECT_ROOT, stdout=log_handle, stderr=subprocess.STDOUT,
                start_new_session=True)
        lock.write_text(str(process.pid), encoding="utf-8")
        watch_job(process, lock)
        flash("Fetching current receipt data. This may take a few minutes.")
    except Exception:
        from web_control.preview_job import save_status
        save_status("failed")
        app.logger.exception("Could not start live preview")
        lock.unlink(missing_ok=True)
        flash("Could not start live preview. Please try again.")
    return redirect(url_for("preview", source="live"))


def _wealth_view():
    from finance.wealth_history import capture_local, review
    from finance.investments import load_investments
    from savings_runway import load_savings
    today = _local_today()
    capture_local(load_savings(PROJECT_ROOT / "data" / "savings.json"),
                  load_investments(PROJECT_ROOT / "data" / "investments.json"), today)
    return review(today, request.args.get("month") or None)


@app.get("/gigs")
@login_required
def gigs_page():
    from services.local_gigs import get_gigs, api_key, options
    settings = load_receipt_settings()
    on = _local_today()
    if request.args.get("date"):
        try:
            on = date.fromisoformat(request.args["date"])
        except ValueError:
            return ("Use a valid date.", 400)
    settings["gigs"] = options()
    settings["features"]["local_gigs"] = settings["gigs"]["enabled"]
    location = validate_location(settings["location"])
    gigs = get_gigs(location, on, int(settings["gigs"]["radius_km"]))
    return render_template("gigs.html", gigs=gigs, settings=settings,
                           key_configured=bool(api_key()), environment_key=bool(os.environ.get("TICKETMASTER_API_KEY")))


@app.post("/gigs/settings")
@login_required
def gigs_settings():
    from services.local_gigs import save_options
    try:
        radius = int(request.form.get("radius_km", "25"))
        limit = int(request.form.get("receipt_limit", "8"))
        if not 1 <= radius <= 100 or not 1 <= limit <= 30:
            raise ValueError("Choose a radius of 1–100 km and 1–30 receipt listings.")
        save_options(radius,limit,request.form.get("enabled") == "on",
                     request.form.get("api_key", ""),request.form.get("clear_key") == "on")
        flash("Local gig settings saved.")
    except (ValueError, OSError) as error:
        flash(str(error))
    return redirect(url_for("gigs_page"))


@app.get("/savings")
@login_required
def savings_review():
    try:
        wealth = _wealth_view()
        error = None
    except (ValueError, OSError, KeyError, TypeError):
        wealth, error = None, "Balance history could not be loaded. Check the month or restore the local history file."
    return render_template("savings_review.html", wealth=wealth, wealth_error=error, today=_local_today())


@app.post("/savings/record")
@login_required
def savings_record():
    from finance.wealth_history import record
    try:
        deposits, withdrawals = request.form.get("deposits", ""), request.form.get("withdrawals", "")
        if bool(deposits) != bool(withdrawals):
            raise ValueError("Fill both cash-flow fields (use zero where applicable), or leave both blank.")
        record(request.form.get("name", ""), request.form.get("kind", ""), request.form.get("date", ""),
               request.form.get("balance", ""), deposits or None, withdrawals or None, today=_local_today())
    except (ValueError, OSError):
        flash("Could not save. Check the account, date, balance and both cash-flow fields.")
    else:
        flash("Dated balance saved privately. Saving the same account, type and date updates that entry.")
    return redirect(url_for("savings_review"))


@app.post("/savings/delete")
@login_required
def savings_delete():
    from finance.wealth_history import delete
    try:
        delete(request.form.get("entry_id", ""))
    except (ValueError, OSError):
        flash("Could not remove this entry.")
    return redirect(url_for("savings_review"))


@app.get("/finance-review")
@login_required
def finance_review():
    from finance.premium_bonds import review as review_bond_prizes
    from finance.commitments import matching_repayment_transaction
    from finance.yearly_subscriptions import annual_subscription_rows
    from services.live_pipeline import (build_subscription_status,
                                        analyse_incoming_payments,
                                        get_account_balances,
                                        get_regular_finance_data,
                                        matching_subscription_transaction)
    today = datetime.now(ZoneInfo("Europe/London")).date()
    try:
        bonds_summary = review_bond_prizes(today)
    except (ValueError, OSError):
        bonds_summary = None
    try:
        wealth, wealth_error = _wealth_view(), None
    except (ValueError, OSError, KeyError, TypeError):
        wealth, wealth_error = None, "Private balance history could not be loaded."
    try:
        finance_data = get_regular_finance_data()
        transactions = finance_data[0]
        try:
            bonds_summary = review_bond_prizes(today)
        except (ValueError, OSError):
            bonds_summary = None
        bank_data_status = finance_data[4].get("bank_data_status", "unavailable")
        status = build_subscription_status(transactions, today=today)
        annual = annual_subscription_rows(status["yearly"], transactions, today)
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
        from web_control.reconciliation import save_review
        try: save_review(transactions, rows, today)
        except (OSError,ValueError): app.logger.warning("Finance review queue could not be saved.")
        payments = external_payments(transactions)
        charts = finance_charts(payments, status["monthly"], today)
        month = monthly_payments(transactions, today)
        salary, other = analyse_incoming_payments(
            transactions,
            salary_payee=load_receipt_settings().get("finance", {}).get("salary_payee", ""),
        )
        income = incoming_review(salary, other, today)
        cash_flow = cash_flow_review(income, payments, today)
        from finance.projection import build_projection
        from finance.receipt import load_finance_settings
        from savings_runway import load_savings, savings_totals
        from web_control.finance_suggestions import build_suggestions
        forecast_settings = load_finance_settings()
        try:
            balances = get_account_balances()
        except Exception:
            app.logger.warning("Cash balances unavailable for finance projection")
            balances = {}
        from finance.wealth_history import apply_latest
        savings_data = load_savings(PROJECT_ROOT / "data" / "savings.json")
        if wealth:
            savings_data, _ = apply_latest(savings_data, {"accounts": []}, wealth)
        savings = savings_totals(savings_data)["runway_accessible"]
        projection = build_projection(balances, transactions, status["monthly"], status["yearly"],
                                      forecast_settings, today, savings, bank_data_status)
        suggestions = build_suggestions(projection, rows, annual, status["ended"], charts,
                                        finance_data[3], transactions, today)
        return render_template("finance_review.html", rows=rows, charts=charts,
                               wealth=wealth, wealth_error=wealth_error, bonds_summary=bonds_summary,
                               month=month, income=income, cash_flow=cash_flow,
                               annual=annual,
                               projection=projection, suggestions=suggestions, forecast_settings=forecast_settings,
                               ended_contracts=status["ended"],
                               bank_data_status=bank_data_status,
                               checked_at=today, checked_time=datetime.now(ZoneInfo("Europe/London")).strftime("%d %b %Y, %H:%M %Z"),
                               accessible_savings=savings, error=None)
    except Exception:
        app.logger.exception("Could not load finance review")
        return render_template("finance_review.html", rows=[], checked_at=today,
                               wealth=wealth, wealth_error=wealth_error, bonds_summary=bonds_summary,
                               error="Bank transactions are unavailable. Try again later."), 503


@app.post("/finance-review/dismiss")
@login_required
def dismiss_finance_suggestion():
    from web_control.finance_suggestions import dismiss_suggestion
    try:
        dismiss_suggestion(request.form.get("suggestion_id", ""), _local_today())
    except ValueError:
        return ("Invalid suggestion", 400)
    return redirect(url_for("finance_review") + "#finance-suggestions")


@app.post("/finance-review/forecast-settings")
@login_required
def save_forecast_settings():
    from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings
    from finance.projection import money
    try:
        settings = load_finance_settings()
        payday = request.form.get("next_payday", "").strip()
        settings["next_payday"] = date.fromisoformat(payday).isoformat() if payday else None
        repeat = request.form.get("payday_repeat", "once")
        if repeat not in {"once", "monthly"}:
            raise ValueError("Invalid payday repeat")
        settings["payday_repeat"] = repeat
        buffer = money(request.form.get("emergency_buffer", "0"))
        daily_text = request.form.get("runway_daily_spend", "").strip()
        daily = money(daily_text) if daily_text else None
        if buffer is None or buffer < 0 or (daily_text and (daily is None or daily < 0)):
            raise ValueError("Enter non-negative amounts")
        settings["emergency_buffer"] = float(buffer)
        settings["runway_daily_spend"] = float(daily) if daily is not None else None
        FINANCE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = FINANCE_SETTINGS_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        temp.replace(FINANCE_SETTINGS_FILE)
        flash("Projection settings saved locally.")
    except (ValueError, OverflowError):
        flash("Enter a valid payday and non-negative amounts.")
    return redirect(url_for("finance_review") + "#finance-forecast")


@app.post("/finance-review/payment/add")
@login_required
def add_forecast_payment():
    from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings
    from finance.projection import money
    try:
        name = request.form.get("name", "").strip()
        amount = money(request.form.get("amount"))
        due = date.fromisoformat(request.form.get("due_date", "")).isoformat()
        repeat = request.form.get("repeat", "once")
        if not name or len(name) > 90 or amount is None or amount <= 0 or repeat not in {"once", "monthly", "yearly"}:
            raise ValueError("Invalid payment")
        settings = load_finance_settings()
        items = settings.setdefault("commitments", [])
        if len(items) >= 100:
            raise ValueError("Too many payments")
        items.append({"name": name, "amount": float(amount), "due_date": due, "repeat": repeat})
        FINANCE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = FINANCE_SETTINGS_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        temp.replace(FINANCE_SETTINGS_FILE)
        flash("Dated payment saved locally.")
    except (ValueError, OverflowError):
        flash("Enter a valid payment name, amount and date.")
    return redirect(url_for("finance_review") + "#finance-forecast")


@app.post("/finance-review/payment/<int:index>/delete")
@login_required
def delete_forecast_payment(index):
    from finance.receipt import FINANCE_SETTINGS_FILE, load_finance_settings
    settings = load_finance_settings()
    items = settings.get("commitments", [])
    if index >= len(items):
        return ("Payment not found", 404)
    items.pop(index)
    temp = FINANCE_SETTINGS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    temp.replace(FINANCE_SETTINGS_FILE)
    return redirect(url_for("finance_review") + "#finance-forecast")


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


# Private archive and backup routes share the existing authentication and CSRF guard.
from web_control.private_tools import register
register(app, login_required, _start_print_command, PROJECT_ROOT, _print_start_lock)
from web_control.premium_bonds import register as register_premium_bonds
register_premium_bonds(app, login_required)

from web_control.delivery_tools import register as register_deliveries
register_deliveries(app, login_required)

from web_control.job_controls import register as register_job_controls
register_job_controls(app, login_required, PROJECT_ROOT, load_print_status, load_live_preview_status)

from web_control.task_tools import register as register_task_tools
register_task_tools(app, login_required)

from web_control.bin_tools import register as register_bin_tools
register_bin_tools(app, login_required)

from web_control.health_tools import register as register_health_tools
register_health_tools(app, login_required)

from web_control.setup_tools import register as register_setup
register_setup(app, login_required, PROJECT_ROOT)

from web_control.reconciliation import register as register_reconciliation
register_reconciliation(app, login_required)
from web_control.daily_tools import register as register_daily_tools
register_daily_tools(app, login_required, PROJECT_ROOT, _start_print_command, _recipe_items, meal_confirmation)

from web_control.savings_goal_tools import register as register_savings_goals
register_savings_goals(app, login_required, _wealth_view)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
