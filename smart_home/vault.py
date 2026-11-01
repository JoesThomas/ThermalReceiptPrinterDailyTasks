"""Passphrase-encrypted credentials; no stored decryption key or plaintext export."""

import base64
from contextlib import contextmanager
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import time
import uuid
from threading import Lock
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from storage import file_lock, write_bytes, write_json

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data" / "smart_home"
ID = re.compile(r"[a-f0-9]{32}")
KINDS = {"camera", "plug", "light", "thermostat", "sensor", "yale_alarm"}
KDF_LOCK = Lock()


def private_dir():
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise ValueError(
            "The secure smart-home vault requires Linux or macOS file permissions."
        )
    # Do not follow linked ancestors into web-served or shared storage.
    if any(p.is_symlink() for p in [DIRECTORY, *DIRECTORY.parents]):
        raise ValueError("Smart-home storage cannot use linked directories.")
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    if DIRECTORY.resolve().is_relative_to((ROOT / "web_control").resolve()):
        raise ValueError("Smart-home storage must be outside the web directory.")
    os.chmod(DIRECTORY, 0o700)


def read_private(path, limit=200000):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != os.geteuid()
            or stat.S_IMODE(meta.st_mode) & 0o077
        ):
            raise ValueError("Smart-home files must be owner-only regular files.")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Smart-home storage exceeds its limit.")
    return raw


def ready():
    return (DIRECTORY / "vault.enc").exists()


def envelope():
    value = json.loads(read_private(DIRECTORY / "vault.enc"))
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "kdf", "salt", "encrypted"}
        or value["version"] != 1
        or value["kdf"] != "scrypt-131072-8-1"
    ):
        raise ValueError("Unsupported smart-home vault format.")
    salt = base64.b64decode(value["salt"], validate=True)
    if len(salt) != 16 or not isinstance(value["encrypted"], str):
        raise ValueError("Invalid smart-home vault.")
    return value, salt


def derive(phrase, salt):
    if not isinstance(phrase, str) or not 16 <= len(phrase) <= 256:
        raise ValueError("Use a smart-home passphrase of 16–256 characters.")
    if not KDF_LOCK.acquire(blocking=False):
        raise ValueError("Another unlock is running; try again shortly.")
    try:
        return base64.urlsafe_b64encode(
            Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(phrase.encode())
        )
    finally:
        KDF_LOCK.release()


def text(value, limit, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid smart-home field.")
    return value


def host(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError(
            "Use the device’s private IPv4 address, without a URL or port."
        ) from None
    if (
        not isinstance(ip, ipaddress.IPv4Address)
        or not any(
            ip in ipaddress.ip_network(cidr)
            for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        or int(ip) & 255 in (0, 255)
    ):
        raise ValueError("Only explicit private LAN IPv4 device addresses are allowed.")
    return str(ip)


def device(values):
    kind = values.get("kind")
    if kind not in KINDS:
        raise ValueError("Unsupported device category.")
    if kind == "yale_alarm":
        username = text(values.get("username", "").strip(), 256)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", username):
            raise ValueError("Use the Yale account email.")
        return dict(
            name=text(values.get("name", "").strip(), 80),
            kind=kind,
            host="Yale cloud (Global)",
            username=username,
            password=text(values.get("password", ""), 256),
            child_id="",
            pin="",
            install_id=values.get("install_id") or str(uuid.uuid4()),
            alarm_id="",
            area_id="",
            yale_auth={},
        )
    child = text(values.get("child_id", ""), 128, empty=True)
    if child and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", child):
        raise ValueError("Invalid hub child ID.")
    return dict(
        name=text(values.get("name", "").strip(), 80),
        kind=kind,
        host=host(values.get("host", "")),
        username=text(values.get("username", ""), 256),
        password=text(values.get("password", ""), 256),
        child_id=child,
        pin="",
    )


def validate(value):
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("devices"), dict)
        or len(value["devices"]) > 20
    ):
        raise ValueError("Invalid smart-home records.")
    if (
        not re.fullmatch(r"[A-Z2-7]{32}", value.get("totp_seed", ""))
        or type(value.get("last_totp")) is not int
    ):
        raise ValueError("Invalid smart-home authenticator.")
    if (
        not isinstance(value.get("recovery"), list)
        or len(value["recovery"]) > 8
        or any(not re.fullmatch(r"[a-f0-9]{64}", s) for s in value["recovery"])
    ):
        raise ValueError("Invalid recovery records.")
    for identifier, row in value["devices"].items():
        if not ID.fullmatch(identifier) or not isinstance(row, dict):
            raise ValueError("Invalid device.")
        device(row)
        if row.get("kind") == "yale_alarm":
            if not re.fullmatch(
                r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                row.get("install_id", ""),
            ):
                raise ValueError("Invalid Yale installation identity.")
            for field in ("alarm_id", "area_id"):
                if row.get(field) and not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,128}", row[field]
                ):
                    raise ValueError("Invalid Yale selection.")
            from smart_home.house_plan import (
                validate as validate_layout,
                empty as empty_layout,
            )

            validate_layout(row.get("layout", empty_layout()))
            auth = row.get("yale_auth", {})
            if (
                not isinstance(auth, dict)
                or set(auth) - {"access", "step"}
                or any(not isinstance(v, str) or len(v) > 8192 for v in auth.values())
            ):
                raise ValueError("Invalid Yale authentication records.")
        if row.get("pin") and not re.fullmatch(r"[a-f0-9]{64}", row["pin"]):
            raise ValueError("Invalid device identity.")
    if not isinstance(value.get("audit"), list) or len(value["audit"]) > 200:
        raise ValueError("Invalid audit records.")


def load(key):
    outer, _ = envelope()
    try:
        value = json.loads(Fernet(key).decrypt(outer["encrypted"].encode(), ttl=None))
        validate(value)
        return value
    except (InvalidToken, TypeError, KeyError):
        raise ValueError("Unlock failed or smart-home storage is damaged.") from None


def save(value, key, salt):
    validate(value)
    encrypted = (
        Fernet(key).encrypt(json.dumps(value, allow_nan=False).encode()).decode()
    )
    raw = json.dumps(
        dict(
            version=1,
            kdf="scrypt-131072-8-1",
            salt=base64.b64encode(salt).decode(),
            encrypted=encrypted,
        )
    ).encode()
    if len(raw) > 200000:
        raise ValueError("Smart-home vault exceeds its limit.")
    write_bytes(DIRECTORY / "vault.enc", raw)


@contextmanager
def transaction(key):
    private_dir()
    with file_lock(DIRECTORY / "vault"):
        _, salt = envelope()
        value = load(key)
        yield value
        save(value, key, salt)


def totp(seed, counter, digits=6):
    digest = hmac.new(
        base64.b32decode(seed), struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 15
    return str(
        (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**digits
    ).zfill(digits)


def counter_for(seed, code, last=-1, now=None):
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        return None
    current = int((time.time() if now is None else now) // 30)
    for counter in (current, current - 1, current + 1):
        if (
            counter > last
            and counter >= 0
            and hmac.compare_digest(totp(seed, counter), code)
        ):
            return counter
    return None


def authenticate(value, code):
    counter = counter_for(value["totp_seed"], code, value["last_totp"])
    if counter is not None:
        value["last_totp"] = counter
        return True
    if re.fullmatch(r"[A-F0-9]{8}(?:-[A-F0-9]{8}){3}", code or ""):
        hashed = hashlib.sha256(code.encode()).hexdigest()
        for index, saved in enumerate(value["recovery"]):
            if hmac.compare_digest(saved, hashed):
                value["recovery"].pop(index)
                return True
    return False


def audit(value, action, identifier="", outcome="ok"):
    value["audit"].append(
        dict(
            at=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            action=action,
            device=identifier,
            outcome=outcome,
        )
    )
    value["audit"] = value["audit"][-200:]


def limited(address, failed=False):
    private_dir()
    now = time.time()
    hashed = hashlib.sha256(address.encode()).hexdigest()
    path = DIRECTORY / "attempts.json"
    with file_lock(DIRECTORY / "attempts"):
        try:
            state = json.loads(read_private(path, 50000))
        except FileNotFoundError:
            state = {}
        if not isinstance(state, dict):
            raise ValueError("Unlock limiter is unavailable.")
        state = {
            k: [
                t
                for t in v
                if isinstance(t, (int, float)) and now - 900 < t <= now + 60
            ]
            for k, v in state.items()
            if isinstance(v, list)
        }
        if failed:
            state.setdefault(hashed, []).append(now)
            state.setdefault("global", []).append(now)
        blocked = len(state.get(hashed, [])) >= 5 or len(state.get("global", [])) >= 20
        # Bounded; global attempts remain effective even with changing addresses.
        state = dict(
            list(
                sorted(state.items(), key=lambda r: max(r[1], default=0), reverse=True)
            )[:128]
        )
        write_json(path, state)
        return blocked
