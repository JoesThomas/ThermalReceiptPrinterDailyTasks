"""New Yale Smart Alarm (Global) cloud protocol; no force-arm, bypass or automation.

Independent bounded client for the public Yale Home mobile protocol. This is not
Yale certification. Older Sync/Smart Living accounts use a different service.
"""

import hashlib
import json
import re
import time
import requests

BASE = "https://api.aaecosystem.com"
# Public application identifier distributed with the Yale Home client, not a user secret.
APPLICATION_ID = "2fcb39a8-40b1-4f4e-bc58-1aeecc0670e0"
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
COMMANDS = {
    "alarm_arm_away": "FULL_ARM",
    "alarm_arm_home": "PARTIAL_ARM",
    "alarm_disarm": "DISARM",
}
STATES = {
    "ARM_STATE_UNSET": "Disarmed",
    "ARM_STATE_PART_ARM": "Armed home",
    "ARM_STATE_ARMED": "Armed away",
}
CONFIRM = {
    "alarm_arm_away": "ARM AWAY",
    "alarm_arm_home": "ARM HOME",
    "alarm_disarm": "DISARM",
}


class Cloud:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.deadline = time.monotonic() + 22

    def close(self):
        self.session.close()

    def request(self, method, path, token="", step="", body=None):
        if time.monotonic() >= self.deadline:
            raise ValueError("Yale deadline reached")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": APPLICATION_ID,
        }
        if token:
            headers["x-access-token"] = token
        if step:
            headers["x-step-token"] = step
        response = self.session.request(
            method,
            BASE + path,
            headers=headers,
            json=body,
            timeout=(3, 6),
            allow_redirects=False,
            stream=True,
        )
        try:
            if not 200 <= response.status_code < 300:
                raise ValueError("Yale request rejected")
            chunks = []
            size = 0
            for chunk in response.iter_content(16384):
                size += len(chunk)
                if size > 250000 or time.monotonic() >= self.deadline:
                    raise ValueError("Yale response limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
            result = json.loads(raw) if raw.strip() else {}
            if isinstance(result, dict) and (
                result.get("error") or result.get("success") is False
            ):
                raise ValueError("Yale request rejected")
            auth = {
                k: response.headers.get(k, "")
                for k in ("x-access-token", "x-step-token")
            }
            if any(len(v) > 8192 for v in auth.values()):
                raise ValueError("Invalid Yale authentication response")
            return result, auth
        finally:
            response.close()


def initial_data():
    return dict(
        model="Yale Smart Alarm",
        mac="",
        fingerprint="",
        readings=[],
        controls=[],
        yale_stage="connect",
        choices=[],
    )


def summarize(row, alarms):
    if not isinstance(alarms, list) or len(alarms) > 50:
        raise ValueError("Invalid alarm list")
    result = initial_data()
    result["yale_stage"] = "choose"
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_id = alarm.get("_id") or alarm.get("id")
        if not isinstance(alarm_id, str) or not IDENTIFIER.fullmatch(alarm_id):
            continue
        status = alarm.get("status") or {}
        if not isinstance(status, dict):
            continue
        for area in status.get("areaArmState") or []:
            if not isinstance(area, dict):
                continue
            area_id = str(area.get("areaID", ""))
            if not IDENTIFIER.fullmatch(area_id):
                continue
            name = str(alarm.get("location") or "Yale alarm")[:80]
            area_name = str(area.get("name") or "Area " + area_id)[:80]
            result["choices"].append(
                dict(alarm_id=alarm_id, area_id=area_id, label=name + " · " + area_name)
            )
            if alarm_id != row.get("alarm_id") or area_id != row.get("area_id"):
                continue
            serial = str(alarm.get("serialNumber") or "")
            if not serial or len(serial) > 128:
                raise ValueError("Missing alarm identity")
            reported = STATES.get(area.get("state"), "Unknown — check Yale app")
            triggered = any(
                str(a.get("areaID")) == area_id and a.get("inAlarm") is True
                for a in status.get("areaAlarmState", [])
                if isinstance(a, dict)
            )
            result.update(
                yale_stage="connected",
                mac=serial,
                identity_label="Hub serial",
                fingerprint=hashlib.sha256(
                    json.dumps([alarm_id, area_id, serial]).encode()
                ).hexdigest(),
                readings=[
                    dict(
                        id="alarm_state",
                        label=area_name,
                        value="TRIGGERED" if triggered else reported,
                        unit="",
                    )
                ],
            )
            if area.get("state") in STATES:
                result["controls"] = [
                    dict(
                        action=action,
                        label=label,
                        confirmation=CONFIRM[action],
                        alarm=True,
                    )
                    for action, label in [
                        ("alarm_arm_home", "Arm home"),
                        ("alarm_arm_away", "Arm away"),
                        ("alarm_disarm", "Disarm alarm"),
                    ]
                ]
    if row.get("alarm_id") and result["yale_stage"] != "connected":
        raise ValueError("Selected alarm area is unavailable")
    if not result["choices"]:
        raise ValueError("No supported new Yale alarm areas found")
    return result


def sensor_reports(items, area_id):
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("Invalid Yale sensor list")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = item.get("_id") or item.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
            continue
        status = item.get("status")
        if not isinstance(status, dict):
            status = {}
        areas = item.get("areaIDs") or status.get("areaIDs")
        if isinstance(areas, list) and areas and area_id not in {str(a) for a in areas}:
            continue
        flags = []
        if status.get("online") is False:
            flags.append("Offline")
        elif status.get("online") is not True:
            flags.append("Connectivity not reported")
        if status.get("lowBattery") is True:
            flags.append("Low battery")
        if status.get("tamperOpen") is True:
            flags.append("Tamper reported")
        if status.get("fault") is True:
            flags.append("Device fault")
        if not areas:
            flags.append("Area membership not reported")
        state, caption = "unknown", "Trigger status unavailable"
        if status.get("inAlarm") is True or status.get("smokeDetected") is True:
            state, caption = "triggered", "Alarm trigger reported"
        elif status.get("online") is False:
            state, caption = "offline", "Offline — current trigger state unknown"
        elif status.get("tamperOpen") is True:
            state, caption = "tamper", "Tamper reported"
        elif status.get("fault") is True:
            state, caption = "fault", "Device fault"
        elif (
            str(item.get("type", "")).startswith(("alarm_contact", "alarm_shock"))
            and type(status.get("contactOpen")) is bool
        ):
            state, caption = (
                ("open", "Door/window open")
                if status["contactOpen"]
                else ("closed", "Door/window closed")
            )
        elif status.get("motionDetected") is True:
            state, caption = "motion", "Motion reported (not proof of an alarm trigger)"
        elif status.get("motionDetected") is False:
            state, caption = "closed", "No motion reported at this check"
        rows.append(
            dict(
                id=hashlib.sha256(identifier.encode()).hexdigest(),
                name=str(item.get("name") or "Yale sensor")[:80],
                kind=str(item.get("type") or "Sensor")[:60],
                state=state,
                label=caption,
                flags=flags,
            )
        )
    return rows


def work(payload):
    row = payload["device"]
    for field in ("alarm_id", "area_id"):
        if row.get(field) and not IDENTIFIER.fullmatch(row[field]):
            return dict(ok=False, error="yale")
    action = payload.get("action", "status")
    value = payload.get("value")
    auth = dict(row.get("yale_auth") or {})
    cloud = Cloud()
    try:
        if not auth.get("access") and not auth.get("step"):
            _, headers = cloud.request(
                "POST",
                "/v2/session/signin",
                body={
                    "identifierType": "email",
                    "identifier": row["username"],
                    "credential": row["password"],
                    "installID": row["install_id"],
                },
            )
            auth = {
                "access": headers["x-access-token"],
                "step": headers["x-step-token"],
            }
        if action in {"yale_send_code", "yale_verify"}:
            if not auth.get("step"):
                raise ValueError("Yale verification session unavailable")
            body = {"identifier": row["username"]}
            if action == "yale_verify":
                if not isinstance(value, str) or not re.fullmatch(r"\d{4,8}", value):
                    raise ValueError("Invalid verification code")
                body["code"] = value
            _, headers = cloud.request(
                "POST",
                "/v2/validation/email"
                if action == "yale_send_code"
                else "/v2/validate/email",
                step=auth["step"],
                body=body,
            )
            if headers["x-step-token"]:
                auth["step"] = headers["x-step-token"]
            if headers["x-access-token"]:
                auth = {"access": headers["x-access-token"], "step": ""}
        if not auth.get("access"):
            if not auth.get("step"):
                raise ValueError("Yale authentication unavailable")
            data = initial_data()
            data["yale_stage"] = "verify"
            data["_yale_auth"] = auth
            return dict(ok=True, data=data)
        alarms, _ = cloud.request("GET", "/users/alarms/mine", token=auth["access"])
        data = summarize(row, alarms)
        if row.get("pin") and data["fingerprint"] != row["pin"]:
            return dict(ok=False, error="identity")
        if action in COMMANDS:
            if not row.get("pin") or not data["fingerprint"] or not data["controls"]:
                raise ValueError("Untrusted alarm area")
            # No automatic retry and no inhibit/bypass/force-arm options.
            cloud.request(
                "PUT",
                f"/alarms/{row['alarm_id']}/state/{COMMANDS[action]}",
                token=auth["access"],
                body={"areaIDs": [row["area_id"]]},
            )
            alarms, _ = cloud.request("GET", "/users/alarms/mine", token=auth["access"])
            data = summarize(row, alarms)
        elif action not in {"status", "yale_verify", "yale_send_code"}:
            raise ValueError("Unsupported alarm operation")
        if data.get("yale_stage") == "connected":
            try:
                items, _ = cloud.request(
                    "GET", f"/alarms/{row['alarm_id']}/devices", token=auth["access"]
                )
                data["sensors"] = sensor_reports(items, row["area_id"])
                data["sensor_warning"] = ""
                if any(r["value"] == "TRIGGERED" for r in data["readings"]) and not any(
                    s["state"] == "triggered" for s in data["sensors"]
                ):
                    data["sensor_warning"] = (
                        "The selected alarm area is triggered, but Yale has not identified the triggering sensor in this response."
                    )
            except Exception:
                data["sensors"] = []
                data["sensor_warning"] = (
                    "Sensor details are unavailable. Mapped sensors are shown as unknown; check the Yale app."
                )
        data["_yale_auth"] = auth
        return dict(ok=True, data=data)
    except Exception:
        # Fail closed; do not translate an unreachable cloud into a disarmed status.
        return dict(ok=False, error="yale")
    finally:
        cloud.close()
