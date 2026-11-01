"""HTTPS-only, separately unlocked direct smart-home controls; no public state API."""

import base64
from functools import wraps
import hashlib
import json
import secrets
import re
import time
from urllib.parse import urlsplit
from flask import (
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from smart_home import vault, sessions, devices
from storage import file_lock


def register(app, login_required, verify_password):
    from web_control.document_tools import TransportSession

    app.session_interface = TransportSession()

    @app.context_processor
    def available():
        return {"smart_home_available": True}

    def binding():
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        return hashlib.sha256(session["csrf_token"].encode()).hexdigest()

    def current():
        return sessions.get(request.cookies.get(sessions.COOKIE, ""), binding())

    def response_redirect(token=None):
        response = redirect(url_for("smart_home_index"))
        if token:
            response.set_cookie(
                sessions.COOKIE,
                token,
                max_age=sessions.TTL,
                secure=True,
                httponly=True,
                samesite="Strict",
                path="/smart-home",
            )
        return response

    def locked_redirect():
        response = response_redirect()
        response.delete_cookie(
            sessions.COOKIE,
            path="/smart-home",
            secure=True,
            httponly=True,
            samesite="Strict",
        )
        return response

    def transport():
        if (
            request.endpoint == "logout"
            or request.endpoint == "login"
            and request.method == "POST"
        ):
            sessions.revoke_binding(binding())
        if not request.path.startswith("/smart-home"):
            return
        if not request.is_secure:
            abort(
                403,
                description="Smart home requires HTTPS, including on localhost. Configure HTTPS before entering any credentials. See docs/smart-home.md.",
            )
        session.modified = True  # Reissue the main login cookie as Secure on HTTPS.
        request.max_content_length = 16384
        request.max_form_memory_size = 16384
        request.max_form_parts = 12
        if request.method == "POST":
            origin = urlsplit(request.headers.get("Origin", ""))
            if (
                origin.scheme != "https"
                or origin.netloc != request.host
                or origin.path
                or origin.query
                or origin.fragment
            ):
                abort(403, description="A same-origin HTTPS form is required.")

    app.before_request_funcs.setdefault(None, []).insert(0, transport)

    @app.after_request
    def headers(response):
        if request.path.startswith("/smart-home"):
            response.headers.update(
                {
                    "Cache-Control": "no-store, private, max-age=0",
                    "Pragma": "no-cache",
                    "Referrer-Policy": "same-origin",
                    "X-Frame-Options": "DENY",
                    "X-Content-Type-Options": "nosniff",
                    "Cross-Origin-Resource-Policy": "same-origin",
                    "Cross-Origin-Opener-Policy": "same-origin",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
                }
            )
            if request.is_secure:
                response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def access(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            row = current()
            if not row or row.get("setup"):
                abort(
                    403, description="Unlock smart home again before accessing devices."
                )
            if row["busy"]:
                abort(429, description="A device request is already running.")
            if not sessions.consume(
                row,
                request.form.get("ticket", ""),
                fn.__name__,
                kwargs.get("identifier", ""),
            ):
                abort(
                    409,
                    description="This form expired or was already used. Refresh the smart-home page.",
                )
            return fn(row, *args, **kwargs)

        return wrapped

    def check_limit():
        if vault.limited(request.remote_addr or "unknown"):
            abort(429, description="Too many unlock attempts. Wait 15 minutes.")

    def fail_unlock():
        vault.limited(request.remote_addr or "unknown", failed=True)
        flash(
            "Smart-home unlock failed. Check the passphrase and a fresh authenticator code or unused recovery code."
        )

    @app.get("/smart-home")
    @login_required
    def smart_home_index():
        row = current()
        records = []
        audit = []
        error = None
        if row and not row.get("setup"):
            try:
                value = vault.load(row["key"])
                records = [
                    dict(
                        id=i,
                        name=d["name"],
                        host=d["host"],
                        kind=d["kind"],
                        paired=bool(d["pin"]),
                        view=row["views"].get(i),
                    )
                    for i, d in value["devices"].items()
                ]
                from smart_home.house_plan import (
                    render as render_plan,
                    empty as empty_plan,
                )

                for record in records:
                    if record["kind"] == "yale_alarm":
                        record["plan"] = render_plan(
                            value["devices"][record["id"]].get("layout", empty_plan()),
                            (record["view"] or {}).get("sensors", []),
                        )
                audit = list(reversed(value["audit"][-20:]))
            except (ValueError, OSError, KeyError):
                sessions.revoke(request.cookies.get(sessions.COOKIE, ""))
                row = None
                records = []
                audit = []
                error = "Smart-home storage is unavailable. It has been locked."
        page_tickets = {}

        def page_ticket(action, identifier=""):
            if not row:
                return ""
            pair = (action, identifier)
            if pair not in page_tickets:
                page_tickets[pair] = sessions.ticket(row, action, identifier)
            return page_tickets[pair]

        return render_template(
            "smart_home.html",
            smart_ready=vault.ready(),
            smart_session=(
                {"setup": True, "seed": row["seed"], "codes": row["codes"]}
                if row and row.get("setup")
                else {"setup": False}
                if row
                else None
            ),
            smart_devices=records,
            smart_audit=audit,
            smart_error=error,
            smart_ticket=page_ticket,
            smart_expires=int(time.time() + max(0, row["expires"] - time.monotonic()))
            if row
            else 0,
        )

    @app.post("/smart-home/setup")
    @login_required
    def smart_home_setup():
        check_limit()
        if vault.ready():
            abort(409, description="Smart home is already configured.")
        if not verify_password(request.form.get("web_password", "")):
            fail_unlock()
            return response_redirect()
        try:
            phrase = request.form.get("passphrase", "")
            if phrase != request.form.get("confirm", ""):
                raise ValueError("Passphrases must match.")
            salt = secrets.token_bytes(16)
            key = vault.derive(phrase, salt)
            seed = base64.b32encode(secrets.token_bytes(20)).decode()
            codes = [
                "-".join([secrets.token_hex(4).upper() for _ in range(4)])
                for _ in range(8)
            ]
            sessions.revoke_binding(binding())
            token = sessions.create(
                binding(), key, setup=True, salt=salt, seed=seed, codes=codes
            )
            return response_redirect(token)
        except (ValueError, OSError):
            vault.limited(request.remote_addr or "unknown", failed=True)
            flash(
                "Setup failed. Use matching 16–256 character passphrases and check private storage."
            )
            return response_redirect()

    @app.post("/smart-home/enrol")
    @login_required
    def smart_home_enrol():
        check_limit()
        row = current()
        if not row or not row.get("setup"):
            abort(403)
        if request.form.get("saved") != "on":
            flash("Save your recovery codes before finishing setup.")
            return response_redirect()
        counter = vault.counter_for(row["seed"], request.form.get("code", ""))
        if counter is None:
            fail_unlock()
            return response_redirect()
        try:
            vault.private_dir()
            with file_lock(vault.DIRECTORY / "vault"):
                if vault.ready():
                    abort(409)
                value = dict(
                    version=1,
                    devices={},
                    totp_seed=row["seed"],
                    last_totp=counter,
                    recovery=[
                        hashlib.sha256(c.encode()).hexdigest() for c in row["codes"]
                    ],
                    audit=[],
                )
                vault.audit(value, "initialise")
                vault.save(value, row["key"], row["salt"])
            key = row["key"]
            sessions.revoke_binding(binding())
            return response_redirect(sessions.create(binding(), key))
        except (OSError, ValueError):
            flash("Encrypted storage could not be created. Check its permissions.")
            return response_redirect()

    @app.post("/smart-home/unlock")
    @login_required
    def smart_home_unlock():
        check_limit()
        try:
            _, salt = vault.envelope()
            key = vault.derive(request.form.get("passphrase", ""), salt)
            with vault.transaction(key) as value:
                if not vault.authenticate(value, request.form.get("code", "")):
                    raise ValueError("Unlock failed")
                vault.audit(value, "unlock")
            sessions.revoke_binding(binding())
            return response_redirect(sessions.create(binding(), key))
        except (ValueError, OSError, KeyError):
            fail_unlock()
            return response_redirect()

    @app.post("/smart-home/lock")
    @login_required
    def smart_home_lock():
        sessions.revoke_binding(binding())
        return locked_redirect()

    @app.post("/smart-home/device")
    @access
    def smart_home_add(row):
        try:
            record = vault.device(request.form)
            with vault.transaction(row["key"]) as value:
                if len(value["devices"]) >= 20:
                    raise ValueError("Device limit reached.")
                if any(
                    d["host"] == record["host"]
                    and d.get("child_id") == record["child_id"]
                    for d in value["devices"].values()
                ):
                    raise ValueError("This address and child device are already saved.")
                value["devices"][secrets.token_hex(16)] = record
                vault.audit(value, "add-device")
            flash(
                "Device saved encrypted. Check its status and identity before trusting it for controls."
            )
        except (ValueError, OSError):
            flash(
                "Device could not be saved. Check the private IPv4 address, fields and device limit."
            )
        return response_redirect()

    @app.post("/smart-home/<identifier>/refresh")
    @access
    def smart_home_refresh(row, identifier):
        operate(row, identifier, "status")
        return response_redirect()

    def operate(row, identifier, action, setting=None):
        with sessions.LOCK:
            if row["busy"] or time.monotonic() - row.get("last_operation", 0) < 1:
                abort(429, description="Wait briefly before another device request.")
            row["busy"] = True
            row["last_operation"] = time.monotonic()
        try:
            value = vault.load(row["key"])
            record = value["devices"].get(identifier)
            if not record:
                abort(404)
            result = devices.run(record, action, setting)
            if current() is not row:
                abort(403, description="Smart-home session expired during the request.")
            private_auth = result.pop("_yale_auth", None)
            result["checked_at"] = time.strftime("%H:%M:%S UTC", time.gmtime())
            with vault.transaction(row["key"]) as value:
                if private_auth is not None and record["kind"] == "yale_alarm":
                    value["devices"][identifier]["yale_auth"] = private_auth
                vault.audit(
                    value, "refresh" if action == "status" else "control", identifier
                )
            row["views"][identifier] = result
            if action == "yale_send_code":
                flash(
                    "Yale verification email requested. Enter the code from Yale here."
                )
            elif action == "yale_verify":
                flash(
                    "Yale verification checked. Select the alarm area or check its reported status."
                )
            elif action.startswith("alarm_"):
                flash(
                    "Yale acknowledged the request. Cloud status may lag during exit delays; confirm the state in the Yale app or on the keypad."
                )
            else:
                flash(
                    "Status checked."
                    if action == "status"
                    else "Command acknowledged by the device. Review the reported state."
                )
        except (ValueError, OSError) as error:
            row["views"].pop(identifier, None)
            try:
                with vault.transaction(row["key"]) as value:
                    vault.audit(
                        value,
                        "refresh" if action == "status" else "control",
                        identifier,
                        outcome="failed or unknown",
                    )
            except (ValueError, OSError):
                pass
            # devices.run only emits fixed, redacted messages; never echo SDK exceptions.
            flash(
                str(error)
                if isinstance(error, ValueError)
                and str(error).startswith(("Device ", "Install ", "Invalid device"))
                else "Smart-home storage or device request failed; no automatic retry was sent."
            )
        finally:
            with sessions.LOCK:
                row["busy"] = False

    @app.post("/smart-home/<identifier>/trust")
    @access
    def smart_home_trust(row, identifier):
        view = row["views"].get(identifier)
        if (
            not view
            or not re.fullmatch(r"[a-f0-9]{64}", view.get("fingerprint", ""))
            or request.form.get("confirm") != "on"
        ):
            abort(
                400,
                description="Check the device MAC against its label and confirm it.",
            )
        try:
            with vault.transaction(row["key"]) as value:
                record = value["devices"].get(identifier)
                if not record or record["pin"]:
                    abort(409)
                record["pin"] = view["fingerprint"]
                vault.audit(value, "trust-device", identifier)
            flash(
                "Device identity saved. It will be checked before each control request."
            )
        except (ValueError, OSError):
            flash("Device identity could not be saved.")
        return response_redirect()

    @app.post("/smart-home/<identifier>/control")
    @access
    def smart_home_control(row, identifier):
        if request.form.get("confirm") != "on":
            abort(400, description="Confirm the physical device change.")
        action = request.form.get("action", "")
        record = vault.load(row["key"])["devices"].get(identifier)
        if not record:
            abort(404)
        if record["kind"] == "yale_alarm":
            from smart_home.yale import CONFIRM

            if (
                action not in CONFIRM
                or request.form.get("command_confirmation") != CONFIRM[action]
            ):
                abort(400, description="Type the exact alarm command confirmation.")
            check_limit()
            with vault.transaction(row["key"]) as value:
                if not vault.authenticate(value, request.form.get("alarm_code", "")):
                    fail_unlock()
                    abort(
                        403,
                        description="A fresh authenticator or unused recovery code is required for every alarm command.",
                    )
        operate(row, identifier, action, request.form.get("value"))
        return response_redirect()

    @app.post("/smart-home/<identifier>/remove")
    @access
    def smart_home_remove(row, identifier):
        if request.form.get("confirm") != "on":
            abort(400)
        try:
            with vault.transaction(row["key"]) as value:
                if identifier not in value["devices"]:
                    abort(404)
                del value["devices"][identifier]
                vault.audit(value, "remove-device", identifier)
            row["views"].pop(identifier, None)
            flash("Device credentials removed from the vault.")
        except (ValueError, OSError):
            flash("Device could not be removed.")
        return response_redirect()

    @app.post("/smart-home/backup")
    @access
    def smart_home_backup(row):
        response = make_response(vault.read_private(vault.DIRECTORY / "vault.enc"))
        response.headers["Content-Type"] = "application/octet-stream"
        response.headers["Content-Disposition"] = (
            "attachment; filename=receipt-smart-home.encrypted.json"
        )
        return response

    @app.post("/smart-home/passphrase")
    @access
    def smart_home_passphrase(row):
        check_limit()
        try:
            phrase = request.form.get("passphrase", "")
            if phrase != request.form.get("confirm", ""):
                raise ValueError("Mismatch")
            salt = secrets.token_bytes(16)
            key = vault.derive(phrase, salt)
            with file_lock(vault.DIRECTORY / "vault"):
                value = vault.load(row["key"])
                if not vault.authenticate(value, request.form.get("code", "")):
                    raise ValueError("Authentication failed")
                vault.audit(value, "change-passphrase")
                vault.save(value, key, salt)
            sessions.revoke_all()
            flash(
                "Smart-home passphrase changed. All smart-home sessions are locked. Use a fresh code to unlock."
            )
            return locked_redirect()
        except (ValueError, OSError):
            fail_unlock()
            return response_redirect()

    @app.post("/smart-home/<identifier>/yale-verify")
    @access
    def smart_home_yale_verify(row, identifier):
        record = vault.load(row["key"])["devices"].get(identifier)
        if not record or record["kind"] != "yale_alarm":
            abort(404)
        action = "yale_verify" if request.form.get("code") else "yale_send_code"
        operate(row, identifier, action, request.form.get("code"))
        return response_redirect()

    @app.post("/smart-home/<identifier>/yale-select")
    @access
    def smart_home_yale_select(row, identifier):
        view = row["views"].get(identifier, {})
        choice = next(
            (
                c
                for c in view.get("choices", [])
                if c["alarm_id"] + "|" + c["area_id"] == request.form.get("selection")
            ),
            None,
        )
        if not choice:
            abort(400)
        with vault.transaction(row["key"]) as value:
            record = value["devices"].get(identifier)
            if not record or record["kind"] != "yale_alarm" or record["pin"]:
                abort(409)
            record["alarm_id"] = choice["alarm_id"]
            record["area_id"] = choice["area_id"]
            vault.audit(value, "select-alarm-area", identifier)
        row["views"].pop(identifier, None)
        flash(
            "Alarm area selected. Check its status and verify the hub identity before using controls."
        )
        return response_redirect()

    @app.post("/smart-home/<identifier>/yale-reconnect")
    @access
    def smart_home_yale_reconnect(row, identifier):
        if request.form.get("confirm") != "on":
            abort(400)
        with vault.transaction(row["key"]) as value:
            record = value["devices"].get(identifier)
            if not record or record["kind"] != "yale_alarm":
                abort(404)
            record["yale_auth"] = {}
            vault.audit(value, "reconnect-yale", identifier)
        row["views"].pop(identifier, None)
        flash(
            "Saved Yale session cleared. Check status to sign in again; this does not change the alarm state."
        )
        return response_redirect()

    @app.post("/smart-home/<identifier>/layout-room")
    @access
    def smart_home_layout_room(row, identifier):
        from smart_home import house_plan

        try:
            with vault.transaction(row["key"]) as value:
                record = value["devices"].get(identifier)
                if not record or record["kind"] != "yale_alarm":
                    abort(404)
                layout = record.setdefault("layout", house_plan.empty())
                if request.form.get("remove") == "on":
                    room_id = request.form.get("room_id")
                    layout["rooms"] = [r for r in layout["rooms"] if r["id"] != room_id]
                    layout["positions"] = {
                        i: p
                        for i, p in layout["positions"].items()
                        if p["room"] != room_id
                    }
                else:
                    house_plan.save_room(layout, request.form)
                house_plan.validate(layout)
                vault.audit(value, "edit-house-layout", identifier)
            flash("Private house layout saved encrypted.")
        except (ValueError, OSError):
            flash(
                "Layout could not be saved. Use valid names and rooms that fit within 0–100 percent, up to four floors."
            )
        return response_redirect()

    @app.post("/smart-home/<identifier>/layout-sensor")
    @access
    def smart_home_layout_sensor(row, identifier):
        from smart_home import house_plan

        try:
            with vault.transaction(row["key"]) as value:
                record = value["devices"].get(identifier)
                if not record or record["kind"] != "yale_alarm":
                    abort(404)
                layout = record.setdefault("layout", house_plan.empty())
                if request.form.get("remove") == "on":
                    layout["positions"].pop(request.form.get("sensor_id"), None)
                else:
                    house_plan.save_sensor(
                        layout,
                        request.form,
                        row["views"].get(identifier, {}).get("sensors", []),
                    )
                house_plan.validate(layout)
                vault.audit(value, "place-alarm-sensor", identifier)
            flash("Sensor position saved encrypted.")
        except (ValueError, OSError):
            flash(
                "Sensor could not be placed. Refresh Yale status and select a room and sensor with valid positions."
            )
        return response_redirect()
