"""New Yale alarm cloud stays separate from old Sync and from automatic controls."""

from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from smart_home import yale, vault, house_plan, sessions
from test_smart_home import SmartWebSetup


def alarm_data(state="ARM_STATE_ARMED", triggered=False):
    return [
        dict(
            _id="alarm-123",
            location="Example house",
            serialNumber="SERIAL-123",
            status=dict(
                areaArmState=[dict(areaID="area-1", name="Downstairs", state=state)],
                areaAlarmState=[dict(areaID="area-1", inAlarm=triggered)],
            ),
        )
    ]


def yale_row(**changes):
    row = vault.device(
        dict(
            name="Private alarm",
            kind="yale_alarm",
            username="owner@example.test",
            password="test-yale-password",
        )
    )
    row.update(alarm_id="alarm-123", area_id="area-1")
    row.update(changes)
    return row


class YaleProtocolTests(TestCase):
    def test_unknown_status_is_never_disarmed_and_no_controls_are_offered(self):
        row = yale_row()
        unknown = yale.summarize(row, alarm_data("UNRECOGNISED"))
        self.assertIn("Unknown", unknown["readings"][0]["value"])
        self.assertEqual(unknown["controls"], [])
        triggered = yale.summarize(row, alarm_data(triggered=True))
        self.assertEqual(triggered["readings"][0]["value"], "TRIGGERED")
        self.assertEqual(
            yale.summarize(row, alarm_data())["readings"][0]["value"], "Armed away"
        )
        with self.assertRaises(ValueError):
            yale.summarize(row, [])

    def test_yale_email_verification_and_private_tokens_are_not_in_status_fields(self):
        cloud = Mock()
        cloud.request.side_effect = [
            ({}, {"x-access-token": "", "x-step-token": "test-step-secret"})
        ]
        with patch.object(yale, "Cloud", return_value=cloud):
            result = yale.work(
                dict(device=yale_row(alarm_id="", area_id=""), action="status")
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["yale_stage"], "verify")
        self.assertEqual(result["data"].pop("_yale_auth")["step"], "test-step-secret")
        self.assertNotIn("test-step-secret", json.dumps(result))
        self.assertEqual(
            cloud.request.call_count, 1
        )  # Email is sent only by explicit request.
        cloud = Mock()
        cloud.request.side_effect = [
            ({}, {"x-access-token": "test-access-secret", "x-step-token": ""}),
            (alarm_data(), {}),
        ]
        with patch.object(yale, "Cloud", return_value=cloud):
            result = yale.work(
                dict(
                    device=yale_row(yale_auth={"step": "step"}),
                    action="yale_verify",
                    value="123456",
                )
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["_yale_auth"]["access"], "test-access-secret")
        self.assertEqual(
            cloud.request.call_args_list[0].args[:2], ("POST", "/v2/validate/email")
        )

    def test_identity_unknown_state_and_unsupported_actions_cannot_disarm(self):
        for row, source, action in [
            (yale_row(pin="0" * 64), alarm_data(), "alarm_disarm"),
            (yale_row(), alarm_data(), "alarm_disarm"),
            (yale_row(), alarm_data(), "panic"),
            (yale_row(), alarm_data("unknown"), "alarm_disarm"),
        ]:
            row["yale_auth"] = {"access": "test-access"}
            cloud = Mock()
            cloud.request.return_value = (source, {})
            with patch.object(yale, "Cloud", return_value=cloud):
                result = yale.work(dict(device=row, action=action))
            self.assertFalse(result["ok"])
            self.assertFalse(
                any(c.args[0] == "PUT" for c in cloud.request.call_args_list)
            )

    def test_command_is_selected_area_only_never_force_arm_or_automatic_retry(self):
        row = yale_row(yale_auth={"access": "test-access"})
        row["pin"] = yale.summarize(row, alarm_data())["fingerprint"]
        cloud = Mock()
        cloud.request.side_effect = [
            (alarm_data(), {}),
            ({}, {}),
            (alarm_data("ARM_STATE_UNSET"), {}),
        ]
        with patch.object(yale, "Cloud", return_value=cloud):
            result = yale.work(dict(device=row, action="alarm_disarm"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["readings"][0]["value"], "Disarmed")
        puts = [c for c in cloud.request.call_args_list if c.args[0] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual(puts[0].args[1], "/alarms/alarm-123/state/DISARM")
        self.assertEqual(puts[0].kwargs["body"], {"areaIDs": ["area-1"]})
        cloud = Mock()
        cloud.request.side_effect = [
            (alarm_data(), {}),
            ValueError("private provider error"),
        ]
        with patch.object(yale, "Cloud", return_value=cloud):
            result = yale.work(dict(device=row, action="alarm_disarm"))
        self.assertEqual(result, dict(ok=False, error="yale"))
        self.assertEqual(
            sum(c.args[0] == "PUT" for c in cloud.request.call_args_list), 1
        )

    def test_verified_tls_fixed_host_no_redirect_proxy_or_credential_query(self):
        response = Mock(status_code=200, headers={})
        response.iter_content.return_value = [b"{}"]
        session = Mock()
        session.request.return_value = response
        with patch("smart_home.yale.requests.Session", return_value=session):
            client = yale.Cloud()
            client.request(
                "POST", "/v2/session/signin", body={"credential": "test-yale-password"}
            )
        self.assertFalse(session.trust_env)
        args, kwargs = session.request.call_args
        self.assertEqual(args[1], "https://api.aaecosystem.com/v2/session/signin")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs.get("verify", True))
        self.assertNotIn("test-yale-password", args[1])
        response.status_code = 302
        with self.assertRaises(ValueError):
            client.request("GET", "/users/alarms/mine")


class YaleProtectedWebTests(SmartWebSetup, TestCase):
    def test_alarm_needs_fresh_mfa_typed_confirmation_and_private_tokens_never_render(
        self,
    ):
        _, codes = self.create()
        with __import__("smart_home.sessions", fromlist=["LOCK"]).LOCK:
            from smart_home import sessions

            row = next(iter(sessions.ROWS.values()))
        identifier = "b" * 32
        record = yale_row(yale_auth={"access": "private-yale-access-token"})
        record["pin"] = yale.summarize(record, alarm_data())["fingerprint"]
        with vault.transaction(row["key"]) as value:
            value["devices"][identifier] = record
        url = f"/smart-home/{identifier}/control"
        base = dict(action="alarm_disarm", confirm="on", command_confirmation="DISARM")
        with patch(
            "web_control.smart_home.devices.run",
            return_value=yale.summarize(record, alarm_data()),
        ) as run:
            self.assertEqual(
                self.post(
                    url,
                    dict(base, ticket=self.ticket("smart_home_control", identifier)),
                ).status_code,
                403,
            )
            run.assert_not_called()
            self.assertEqual(
                self.post(
                    url,
                    dict(
                        base,
                        ticket=self.ticket("smart_home_control", identifier),
                        command_confirmation="wrong",
                        alarm_code=codes[0],
                    ),
                ).status_code,
                400,
            )
            run.assert_not_called()
            self.assertEqual(
                self.post(
                    url,
                    dict(
                        base,
                        ticket=self.ticket("smart_home_control", identifier),
                        alarm_code=codes[0],
                    ),
                ).status_code,
                302,
            )
            run.assert_called_once()
            row["last_operation"] = 0
            self.assertEqual(
                self.post(
                    url,
                    dict(
                        base,
                        ticket=self.ticket("smart_home_control", identifier),
                        alarm_code=codes[0],
                    ),
                ).status_code,
                403,
            )
            self.assertEqual(run.call_count, 1)
        row["last_operation"] = 0
        result = yale.summarize(record, alarm_data())
        result["_yale_auth"] = {"access": "new-private-yale-token", "step": ""}
        with patch("web_control.smart_home.devices.run", return_value=deepcopy(result)):
            self.post(
                f"/smart-home/{identifier}/refresh",
                dict(ticket=self.ticket("smart_home_refresh", identifier)),
            )
        self.assertNotIn("_yale_auth", row["views"][identifier])
        self.assertEqual(
            vault.load(row["key"])["devices"][identifier]["yale_auth"]["access"],
            "new-private-yale-token",
        )
        html = self.get().get_data(as_text=True)
        for secret in [
            "new-private-yale-token",
            "private-yale-access-token",
            "test-yale-password",
            "owner@example.test",
        ]:
            self.assertNotIn(secret, html)
        self.assertIn("Fresh smart-home authenticator", html)
        self.assertIn("Type DISARM", html)


class HousePlanTests(TestCase):
    def test_geometry_and_sensor_identity_are_bounded(self):
        plan = house_plan.empty()
        fields = dict(name="Hall", floor="Ground", x=5, y=5, w=40, h=50)
        room = house_plan.save_room(plan, fields)
        sensor = dict(
            id="a" * 64,
            name="Front door",
            state="open",
            label="Door/window open",
            flags=[],
        )
        house_plan.save_sensor(
            plan, dict(sensor_id=sensor["id"], room_id=room, x=50, y=50), [sensor]
        )
        marker = house_plan.render(plan, [sensor])["floors"][0]["markers"][0]
        self.assertEqual(marker["state"], "open")
        self.assertEqual(marker["cx"], 270)
        missing = house_plan.render(plan, [])["floors"][0]["markers"][0]
        self.assertEqual(missing["state"], "unknown")
        self.assertIn("No sensor report", missing["flags"][0])
        for changes in [
            dict(x=99),
            dict(w="nan"),
            dict(h=-1),
            dict(name="\n"),
            dict(room_id="b" * 32),
        ]:
            with self.assertRaises(ValueError):
                house_plan.save_room(deepcopy(plan), dict(fields, **changes))
        for malformed in [dict(id=[]), dict(id=3)]:
            bad = deepcopy(plan)
            bad["rooms"][0].update(malformed)
            with self.assertRaises(ValueError):
                house_plan.validate(bad)
        with self.assertRaises(ValueError):
            house_plan.save_sensor(plan, dict(sensor_id="b" * 64), [sensor])

    def test_sensor_states_do_not_invent_alarm_triggers_or_all_clear(self):
        rows = [
            dict(
                _id="door",
                type="alarm_contact",
                status=dict(contactOpen=True, online=True),
            ),
            dict(_id="closed", type="alarm_contact", status=dict(contactOpen=False)),
            dict(_id="missing", type="alarm_pir", status=dict(online=True)),
            dict(_id="motion", status=dict(motionDetected=True)),
            dict(_id="trigger", status=dict(inAlarm=True, lowBattery=True)),
            dict(
                _id="offline",
                type="alarm_contact",
                status=dict(online=False, contactOpen=False),
            ),
            dict(_id="tamper", status=dict(tamperOpen=True)),
            dict(_id="fault", status=dict(fault=True)),
            dict(_id="other", areaIDs=["other"], status=dict(inAlarm=True)),
        ]
        reports = yale.sensor_reports(rows, "area-1")
        self.assertEqual(
            [s["state"] for s in reports],
            [
                "open",
                "closed",
                "unknown",
                "motion",
                "triggered",
                "offline",
                "tamper",
                "fault",
            ],
        )
        self.assertTrue(all(len(s["id"]) == 64 for s in reports))
        self.assertIn("not proof", reports[3]["label"])
        self.assertIn("Low battery", reports[4]["flags"])
        row = yale_row(yale_auth={"access": "test-access"})
        cloud = Mock()
        cloud.request.side_effect = [(alarm_data(triggered=True), {}), (rows[:3], {})]
        with patch.object(yale, "Cloud", return_value=cloud):
            result = yale.work(dict(device=row, action="status"))
        self.assertTrue(result["ok"])
        self.assertIn("has not identified", result["data"]["sensor_warning"])
        self.assertEqual(result["data"]["sensors"][2]["state"], "unknown")


class HousePlanProtectedTests(SmartWebSetup, TestCase):
    def test_layout_is_encrypted_access_controlled_and_missing_reports_unknown(self):
        self.create()
        row = next(iter(sessions.ROWS.values()))
        identifier = "b" * 32
        with vault.transaction(row["key"]) as value:
            value["devices"][identifier] = yale_row()
        sensor = dict(
            id="a" * 64,
            name="Private door",
            state="triggered",
            label="Alarm trigger reported",
            flags=[],
        )
        row["views"][identifier] = dict(
            sensors=[sensor], readings=[], controls=[], checked_at="Test time"
        )
        self.assertEqual(
            self.post(
                f"/smart-home/{identifier}/layout-room",
                dict(name="Private hall", floor="Ground", x=5, y=5, w=50, h=50),
            ).status_code,
            409,
        )
        result = self.post(
            f"/smart-home/{identifier}/layout-room",
            dict(
                ticket=self.ticket("smart_home_layout_room", identifier),
                name="Private hall",
                floor="Ground",
                x=5,
                y=5,
                w=50,
                h=50,
            ),
        )
        self.assertEqual(result.status_code, 302)
        room = vault.load(row["key"])["devices"][identifier]["layout"]["rooms"][0]["id"]
        result = self.post(
            f"/smart-home/{identifier}/layout-sensor",
            dict(
                ticket=self.ticket("smart_home_layout_sensor", identifier),
                sensor_id=sensor["id"],
                room_id=room,
                x=50,
                y=50,
            ),
        )
        self.assertEqual(result.status_code, 302)
        html = self.get().get_data(as_text=True)
        self.assertIn("Private hall", html)
        self.assertIn("smart-sensor-triggered", html)
        row["views"].clear()
        self.assertIn("smart-sensor-unknown", self.get().get_data(as_text=True))
        backup = self.post(
            "/smart-home/backup", dict(ticket=self.ticket("smart_home_backup"))
        )
        for text in [b"Private hall", b"Private door", b"test-yale-password"]:
            self.assertNotIn(text, backup.data)
            self.assertNotIn(text, (vault.DIRECTORY / "vault.enc").read_bytes())
        self.post("/smart-home/lock")
        self.assertNotIn("Private hall", self.get().get_data(as_text=True))
        self.assertEqual(
            self.post(
                f"/smart-home/{identifier}/layout-room", dict(name="Unprotected")
            ).status_code,
            403,
        )
