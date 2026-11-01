"""Independent MFA, encryption, strict transport and allowlisted physical commands."""

import asyncio
import base64
from copy import deepcopy
from datetime import datetime
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch
import sys
import time
from flask import Flask, abort, redirect, request, session
from jinja2 import ChoiceLoader, DictLoader
from cryptography.fernet import Fernet
from smart_home import vault, sessions, devices, worker
from web_control.smart_home import register

ROOT = Path(__file__).resolve().parents[1]
PHRASE = "test-only separate vault passphrase"
SEED = base64.b32encode(b"12345678901234567890").decode()


def payload():
    return dict(
        version=1, devices={}, totp_seed=SEED, last_totp=-1, recovery=[], audit=[]
    )


def record(**changes):
    return dict(
        dict(
            name="Private camera",
            kind="camera",
            host="192.168.1.50",
            username="test-user",
            password="test-camera-password",
            child_id="",
            pin="",
        ),
        **changes,
    )


def fake_feature(value, *, low=0, high=100, unit=""):
    return SimpleNamespace(
        value=value,
        name="Example feature",
        unit=unit,
        attribute_setter="set",
        minimum_value=low,
        maximum_value=high,
        set_value=AsyncMock(),
    )


def fake_device(kind="camera"):
    return SimpleNamespace(
        host="192.168.1.50",
        device_type=SimpleNamespace(value=kind),
        features={"state": fake_feature(True)},
        mac="AA:BB:CC:DD:EE:FF",
        model="C212",
        device_id="test-device-id",
        children=[],
        disconnect=AsyncMock(),
        update=AsyncMock(),
    )


class SmartVaultTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(vault, "DIRECTORY", Path(self.tmp.name) / "private")
        p.start()
        self.addCleanup(p.stop)
        sessions.revoke_all()
        self.addCleanup(sessions.revoke_all)

    def test_scrypt_encryption_integrity_permissions_and_no_plaintext_key(self):
        salt = b"1" * 16
        key = vault.derive(PHRASE, salt)
        vault.private_dir()
        value = payload()
        value["devices"]["a" * 32] = record()
        vault.save(value, key, salt)
        raw = (vault.DIRECTORY / "vault.enc").read_bytes()
        for secret in [
            PHRASE,
            "test-camera-password",
            "test-user",
            "192.168.1.50",
            "Private camera",
            SEED,
            key.decode(),
        ]:
            self.assertNotIn(secret.encode(), raw)
        self.assertEqual(vault.load(key), value)
        self.assertEqual(os.stat(vault.DIRECTORY / "vault.enc").st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(vault.DIRECTORY).st_mode & 0o777, 0o700)
        with self.assertRaises(ValueError):
            vault.load(Fernet.generate_key())
        path = vault.DIRECTORY / "vault.enc"
        saved = path.read_bytes()
        path.unlink()
        path.symlink_to(Path(self.tmp.name) / "outside")
        with self.assertRaises(OSError):
            vault.envelope()
        path.unlink()
        path.write_bytes(saved)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            vault.envelope()

    def test_totp_rfc_vector_window_and_recovery_codes_are_single_use(self):
        # RFC 6238 SHA-1 test vector, eight-digit form at 59 seconds.
        self.assertEqual(vault.totp(SEED, 1, 8), "94287082")
        code = vault.totp(SEED, 100)
        self.assertEqual(vault.counter_for(SEED, code, now=3000), 100)
        self.assertIsNone(vault.counter_for(SEED, code, last=100, now=3000))
        self.assertIsNone(vault.counter_for(SEED, code, now=3150))
        value = payload()
        recovery = "ABCD1234-" * 3 + "ABCD1234"
        value["recovery"] = [hashlib.sha256(recovery.encode()).hexdigest()]
        with patch("smart_home.vault.time.time", return_value=3000):
            self.assertTrue(vault.authenticate(value, code))
            self.assertFalse(vault.authenticate(value, code))
            self.assertTrue(vault.authenticate(value, recovery))
            self.assertFalse(vault.authenticate(value, recovery))

    def test_private_literal_addresses_and_limits(self):
        for address in [
            "127.0.0.1",
            "169.254.169.254",
            "8.8.8.8",
            "localhost",
            "https://192.168.1.2",
            "192.168.1.2:80",
            "::1",
            "10.0.0.0",
            "192.168.1.255",
        ]:
            with self.assertRaises(ValueError, msg=address):
                vault.host(address)
        self.assertEqual(vault.host("192.168.1.50"), "192.168.1.50")
        for name in ["x\nsecret", ""]:
            with self.assertRaises(ValueError):
                vault.device(record(name=name))
        for _ in range(5):
            vault.limited("client", failed=True)
        self.assertTrue(vault.limited("client"))
        self.assertFalse(vault.limited("different-client"))
        with patch("smart_home.vault.time.time", return_value=time.time() + 901):
            self.assertFalse(vault.limited("client"))

    def test_server_sessions_bind_expire_revoke_and_consume_tickets(self):
        with patch("smart_home.sessions.time.monotonic", return_value=100):
            sid = sessions.create("binding", b"key")
            row = sessions.get(sid, "binding")
            self.assertIsNone(sessions.get(sid, "other"))
            ticket = sessions.ticket(row, "control", "device")
            self.assertTrue(sessions.consume(row, ticket, "control", "device"))
            self.assertFalse(sessions.consume(row, ticket, "control", "device"))
        with patch("smart_home.sessions.time.monotonic", return_value=401):
            self.assertIsNone(sessions.get(sid, "binding"))
        sid = sessions.create("binding", b"key")
        sessions.revoke_binding("binding")
        self.assertIsNone(sessions.get(sid, "binding"))


class SmartDeviceTests(TestCase):
    def test_camera_privacy_is_reversed_and_thermostat_settings_are_capability_gated(
        self,
    ):
        dev = fake_device()
        dev.features.update(pan_left=fake_feature(None), pan_step=fake_feature(30))
        asyncio.run(devices.apply(dev, "camera", "privacy_on", None))
        dev.features["state"].set_value.assert_awaited_with(False)
        asyncio.run(devices.apply(dev, "camera", "privacy_off", None))
        dev.features["state"].set_value.assert_awaited_with(True)
        asyncio.run(devices.apply(dev, "camera", "pan_left", None))
        dev.features["pan_step"].set_value.assert_awaited_with(5)
        with self.assertRaises(ValueError):
            asyncio.run(devices.apply(dev, "camera", "target_temperature", 20))
        thermostat = fake_device("thermostat")
        thermostat.features["target_temperature"] = fake_feature(
            19, low=5, high=35, unit="°C"
        )
        asyncio.run(
            devices.apply(thermostat, "thermostat", "target_temperature", "20.5")
        )
        for value in ["nan", "inf", "31", "4", "20.1"]:
            with self.assertRaises(ValueError):
                asyncio.run(
                    devices.apply(thermostat, "thermostat", "target_temperature", value)
                )
        thermostat.features["target_temperature"].unit = ""
        thermostat.features["temperature_unit"] = fake_feature("celsius")
        self.assertTrue(
            any(
                c["action"] == "target_temperature"
                for c in devices.describe(thermostat, "thermostat")["controls"]
            )
        )
        thermostat.features["temperature_unit"].value = "fahrenheit"
        thermostat.features["target_temperature"].unit = "°F"
        self.assertFalse(
            any(
                c["action"] == "target_temperature"
                for c in devices.describe(thermostat, "thermostat")["controls"]
            )
        )
        with self.assertRaises(ValueError):
            devices.describe(dev, "plug")

    def test_worker_checks_identity_before_commands_and_never_returns_credentials(self):
        dev = fake_device()
        fake = SimpleNamespace(
            Credentials=lambda *a: a,
            Discover=SimpleNamespace(discover_single=AsyncMock(return_value=dev)),
        )
        with patch.dict(sys.modules, {"kasa": fake}):
            result = asyncio.run(
                worker.work(dict(device=record(pin="0" * 64), action="privacy_off"))
            )
            self.assertEqual(result["error"], "identity")
            dev.features["state"].set_value.assert_not_awaited()
            result = asyncio.run(worker.work(dict(device=record(), action="status")))
            self.assertTrue(result["ok"])
            self.assertNotIn("password", json.dumps(result))
            self.assertNotIn("username", json.dumps(result))
            pin = result["data"]["fingerprint"]
            self.assertTrue(
                asyncio.run(
                    worker.work(dict(device=record(pin=pin), action="privacy_on"))
                )["ok"]
            )
            dev.features["state"].set_value.assert_awaited_with(False)

    def test_worker_subprocess_uses_stdin_not_arguments_or_logs_and_has_deadline(self):
        value = dict(ok=True, data={"controls": []})
        with patch(
            "smart_home.devices.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(value).encode()
            ),
        ) as run:
            devices.run(record())
            args, kwargs = run.call_args
            self.assertNotIn("test-camera-password", str(args))
            self.assertNotIn("192.168.1.50", str(args))
            self.assertIn(b"test-camera-password", kwargs["input"])
            self.assertEqual(kwargs["timeout"], 18)
            self.assertIs(kwargs.get("shell", False), False)
        import subprocess

        with patch(
            "smart_home.devices.subprocess.run",
            side_effect=subprocess.TimeoutExpired("worker", 18),
        ):
            with self.assertRaisesRegex(ValueError, "may have arrived"):
                devices.run(record(), "privacy_off")


class SmartWebSetup:
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(vault, "DIRECTORY", Path(self.tmp.name) / "smart")
        p.start()
        self.addCleanup(p.stop)
        # Fast deterministic KDF only for route tests; the real KDF is exercised above.
        p = patch.object(
            vault,
            "derive",
            side_effect=lambda phrase, salt: base64.urlsafe_b64encode(
                hashlib.sha256(phrase.encode() + salt).digest()
            ),
        )
        p.start()
        self.addCleanup(p.stop)
        sessions.revoke_all()
        self.addCleanup(sessions.revoke_all)
        self.app = Flask(
            __name__, template_folder=str(ROOT / "web_control" / "templates")
        )
        self.app.secret_key = "test-only"
        self.app.jinja_loader = ChoiceLoader(
            [
                DictLoader({"navigation.html": "", "favicon.html": ""}),
                self.app.jinja_loader,
            ]
        )
        self.app.jinja_env.globals["csrf_token"] = lambda: session["csrf_token"]

        @self.app.before_request
        def csrf():
            if request.method == "POST" and request.form.get(
                "csrf_token"
            ) != session.get("csrf_token"):
                abort(403)

        def login_required(fn):
            @wraps(fn)
            def wrapped(*a, **k):
                return (
                    fn(*a, **k) if session.get("authenticated") else redirect("/login")
                )

            return wrapped

        register(self.app, login_required, lambda p: p == "web-secret")

        @self.app.post("/logout", endpoint="logout")
        def logout():
            session.clear()
            return "logged out"

        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s.update(authenticated=True, csrf_token="csrf-test")

    def post(self, path, data=None, **kwargs):
        return self.client.post(
            path,
            data={"csrf_token": "csrf-test", **(data or {})},
            base_url="https://localhost",
            headers={"Origin": "https://localhost"},
            **kwargs,
        )

    def get(self):
        return self.client.get("/smart-home", base_url="https://localhost")

    def create(self):
        self.assertEqual(
            self.post(
                "/smart-home/setup",
                dict(web_password="web-secret", passphrase=PHRASE, confirm=PHRASE),
            ).status_code,
            302,
        )
        with sessions.LOCK:
            row = next(iter(sessions.ROWS.values()))
        seed = row["seed"]
        codes = list(row["codes"])
        self.assertFalse(vault.ready())
        self.assertEqual(
            self.post(
                "/smart-home/enrol",
                dict(code=vault.totp(seed, int(time.time() // 30)), saved="on"),
            ).status_code,
            302,
        )
        self.assertTrue(vault.ready())
        return seed, codes

    def ticket(self, action, identifier=""):
        with sessions.LOCK:
            row = next(r for r in sessions.ROWS.values() if not r.get("setup"))
        return sessions.ticket(row, action, identifier)


class SmartWebTests(SmartWebSetup, TestCase):
    def test_https_login_origin_csrf_and_locked_routes_fail_closed(self):
        self.assertEqual(self.client.get("/smart-home").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/smart-home/setup", data={"web_password": "secret"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/smart-home/setup",
                data={"csrf_token": "csrf-test"},
                base_url="https://localhost",
                headers={"Origin": "https://evil.example"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/smart-home/setup",
                base_url="https://localhost",
                headers={"Origin": "https://localhost"},
            ).status_code,
            403,
        )
        self.assertEqual(self.post("/smart-home/device").status_code, 403)
        response = self.get()
        self.assertEqual(response.status_code, 200)
        for name, value in [
            ("Cache-Control", "no-store"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "same-origin"),
        ]:
            self.assertIn(value, response.headers[name])
        with self.client.session_transaction() as s:
            s.clear()
        self.assertEqual(self.get().status_code, 302)

    def test_encrypted_setup_commands_one_use_lock_logout_and_no_passwords_in_page(
        self,
    ):
        _, codes = self.create()
        cookie = self.client.get_cookie(sessions.COOKIE, path="/smart-home")
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, "Strict")
        self.assertNotIn(PHRASE, cookie.value)
        self.assertEqual(
            self.post(
                "/smart-home/device",
                dict(record(), ticket=self.ticket("smart_home_add")),
            ).status_code,
            302,
        )
        with sessions.LOCK:
            row = next(iter(sessions.ROWS.values()))
        value = vault.load(row["key"])
        identifier = next(iter(value["devices"]))
        self.assertFalse(value["devices"][identifier]["pin"])
        view = devices.describe(fake_device(), "camera")
        ticket = self.ticket("smart_home_refresh", identifier)
        with patch("web_control.smart_home.devices.run", return_value=view) as run:
            self.post(f"/smart-home/{identifier}/refresh", dict(ticket=ticket))
            self.assertEqual(
                self.post(
                    f"/smart-home/{identifier}/refresh", dict(ticket=ticket)
                ).status_code,
                409,
            )
            run.assert_called_once()
        self.post(
            f"/smart-home/{identifier}/trust",
            dict(ticket=self.ticket("smart_home_trust", identifier), confirm="on"),
        )
        row["last_operation"] = 0
        with patch("web_control.smart_home.devices.run", return_value=view) as run:
            self.post(
                f"/smart-home/{identifier}/control",
                dict(
                    ticket=self.ticket("smart_home_control", identifier),
                    confirm="on",
                    action="privacy_on",
                ),
            )
            run.assert_called_once()
        html = self.get().get_data(as_text=True)
        self.assertIn("Private camera", html)
        for secret in [PHRASE, "test-camera-password", "test-user", *codes]:
            self.assertNotIn(secret, html)
        backup = self.post(
            "/smart-home/backup", dict(ticket=self.ticket("smart_home_backup"))
        )
        self.assertEqual(backup.status_code, 200)
        self.assertNotIn(b"test-camera-password", backup.data)
        self.post("/smart-home/lock")
        self.assertNotIn("Private camera", self.get().get_data(as_text=True))
        self.assertEqual(self.post("/smart-home/device").status_code, 403)
        self.post("/smart-home/unlock", dict(passphrase=PHRASE, code=codes[0]))
        self.assertTrue(sessions.ROWS)
        self.post("/logout")
        self.assertFalse(sessions.ROWS)

    def test_recovery_code_cannot_replay_and_expiry_cannot_be_extended_by_cookie(self):
        _, codes = self.create()
        self.post("/smart-home/lock")
        self.post("/smart-home/unlock", dict(passphrase=PHRASE, code=codes[0]))
        self.assertIn("Private device controls", self.get().get_data(as_text=True))
        self.post("/smart-home/lock")
        self.post("/smart-home/unlock", dict(passphrase=PHRASE, code=codes[0]))
        self.assertFalse(sessions.ROWS)
        self.post("/smart-home/unlock", dict(passphrase=PHRASE, code=codes[1]))
        with sessions.LOCK:
            row = next(iter(sessions.ROWS.values()))
            row["expires"] = time.monotonic() - 1
        self.assertEqual(self.post("/smart-home/backup").status_code, 403)

    def test_passphrase_change_revokes_sessions_and_old_phrase(self):
        _, codes = self.create()
        new_phrase = "another test-only separate passphrase"
        self.post(
            "/smart-home/passphrase",
            dict(
                ticket=self.ticket("smart_home_passphrase"),
                passphrase=new_phrase,
                confirm=new_phrase,
                code=codes[0],
            ),
        )
        self.assertFalse(sessions.ROWS)
        self.post("/smart-home/unlock", dict(passphrase=PHRASE, code=codes[1]))
        self.assertFalse(sessions.ROWS)
        self.post("/smart-home/unlock", dict(passphrase=new_phrase, code=codes[1]))
        self.assertTrue(sessions.ROWS)
