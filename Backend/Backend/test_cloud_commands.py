import unittest
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import cloud_accounts as accounts
import cloud_commands as commands
from cloud_account_api import build_router


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.account, self.home, self.gateway, self.command_id = (uuid4() for _ in range(4))
        self.credential = "test-only-machine-credential-32-characters"
        self.payload = commands.CommandInput(
            command_id=self.command_id, mac="aa:bb:cc:dd:ee:ff", action="block",
        )
        self.command = {
            "id": self.command_id, "gateway_id": self.gateway, "created_by": self.account,
            "mac": self.payload.mac, "action": "block", "status": "queued",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=120),
        }

    @contextmanager
    def connection(self, rows):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.side_effect = rows
        yield self.db

    def test_nonmember_wrong_household_and_member_cannot_enqueue(self):
        for row, status in ((None, 404), ({"role": "member"}, 403)):
            with patch.object(commands, "connect", side_effect=lambda: self.connection([row])):
                with self.assertRaises(HTTPException) as caught:
                    commands.create_command(self.account, self.home, self.gateway, self.payload)
            self.assertEqual(caught.exception.status_code, status)
            self.assertEqual(self.db.execute.call_count, 1)
            self.assertEqual(self.db.execute.call_args.args[1], (self.gateway, self.home, self.account))

    def test_training_is_gateway_scoped_flagged_and_does_not_require_fake_device(self):
        payload = commands.CommandInput(command_id=self.command_id, action="train")
        with patch.dict(os.environ, {"GHOST_CLOUD_TRAINING_ENABLED": "false"}):
            with self.assertRaises(HTTPException) as error:
                commands.create_command(self.account, self.home, self.gateway, payload)
        self.assertEqual(error.exception.status_code, 503)
        command = {**self.command, "action": "train", "mac": None}
        with (
            patch.dict(os.environ, {"GHOST_CLOUD_TRAINING_ENABLED": "true"}),
            patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"role": "owner"}, None, None, command,
            ])),
        ):
            result = commands.create_command(self.account, self.home, self.gateway, payload)
        self.assertEqual(result["status"], "queued")
        self.assertFalse(any("devices @>" in call.args[0] for call in self.db.execute.call_args_list))
        self.assertIsNone(self.db.execute.call_args.args[1][4])
        for change in (
            {"mac": self.payload.mac}, {"device_name": "Sensor"}, {"ip_address": ""},
        ):
            with self.assertRaises(ValidationError):
                commands.CommandInput(command_id=self.command_id, action="train", **change)
        with self.assertRaises(ValidationError):
            commands.CommandInput(command_id=self.command_id, action="block")

    def test_training_preserves_household_roles_and_no_redelivery(self):
        payload = commands.CommandInput(command_id=self.command_id, action="train")
        for member, status in ((None, 404), ({"role": "member"}, 403)):
            with (
                patch.dict(os.environ, {"GHOST_CLOUD_TRAINING_ENABLED": "true"}),
                patch.object(commands, "connect", side_effect=lambda: self.connection([member])),
            ):
                with self.assertRaises(HTTPException) as error:
                    commands.create_command(self.account, self.home, self.gateway, payload)
                self.assertEqual(error.exception.status_code, status)
        with patch.object(commands, "connect", side_effect=lambda: self.connection([
            {"household_id": self.home}, {**self.command, "action": "train", "mac": None},
            {"role": "admin"}, {"id": self.command_id},
        ])):
            result = commands.take_command(self.gateway, self.credential)
        self.assertEqual(result["command"]["action"], "train")
        self.assertIsNone(result["command"]["mac"])
        self.assertIn("status = 'queued'", self.db.execute.call_args_list[2].args[0])

    def test_registration_accepts_new_device_only_after_explicit_pi_rollout(self):
        payload = commands.CommandInput(command_id=self.command_id, action="register",
            mac=self.payload.mac, device_name="New sensor", ip_address="")
        with patch.dict(os.environ, {"GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED": "false"}):
            with self.assertRaises(HTTPException) as caught:
                commands.create_command(self.account, self.home, self.gateway, payload)
            self.assertEqual(caught.exception.status_code, 503)
        with (
            patch.dict(os.environ, {"GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED": "true"}),
            patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"role": "owner"}, None, None, None,
                {**self.command, "action": "register", "device_name": "New sensor", "ip_address": ""},
            ])),
        ):
            self.assertEqual(commands.create_command(self.account, self.home, self.gateway, payload)["action"], "register")
        self.assertEqual(self.db.execute.call_args.args[1][-2:], ("New sensor", ""))

    def test_registration_details_are_validated_and_bound_to_idempotency(self):
        for changes in (
            {"device_name": " "}, {"ip_address": "https://example.invalid"},
            {"ip_address": "127.0.0.1;reboot"}, {"device_name": None},
        ):
            with self.assertRaises(ValidationError):
                commands.CommandInput(command_id=self.command_id, action="register", mac=self.payload.mac,
                    **{"device_name": "Sensor", "ip_address": "", **changes})
        with self.assertRaises(ValidationError):
            commands.CommandInput(**{**self.payload.model_dump(), "device_name": "unexpected"})
        payload = commands.CommandInput(command_id=self.command_id, action="register",
            mac=self.payload.mac, device_name="Sensor", ip_address="")
        with (
            patch.dict(os.environ, {"GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED": "true"}),
            patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"role": "owner"}, {**self.command, "action": "register", "device_name": "Other", "ip_address": ""},
            ])),
            self.assertRaises(HTTPException),
        ):
            commands.create_command(self.account, self.home, self.gateway, payload)

    def test_owner_and_admin_queue_but_do_not_mark_success(self):
        for role in ("owner", "admin"):
            with patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"role": role}, None, None, {"present": 1}, self.command,
            ])):
                result = commands.create_command(self.account, self.home, self.gateway, self.payload)
            self.assertEqual(result["status"], "queued")
            self.assertIn("FOR UPDATE OF g FOR SHARE OF m", self.db.execute.call_args_list[0].args[0])
            self.assertIn("devices @>", self.db.execute.call_args_list[4].args[0])

    def test_active_command_and_unregistered_device_rejected(self):
        for rows, status in (
            ([{"role": "owner"}, None, {"id": uuid4()}], 409),
            ([{"role": "owner"}, None, None, None], 404),
        ):
            with patch.object(commands, "connect", side_effect=lambda: self.connection(rows)):
                with self.assertRaises(HTTPException) as caught:
                    commands.create_command(self.account, self.home, self.gateway, self.payload)
            self.assertEqual(caught.exception.status_code, status)
            self.assertFalse(any("INSERT INTO" in call.args[0] for call in self.db.execute.call_args_list))

    def test_idempotency_is_bound_to_creator_gateway_and_payload(self):
        for changes in ({}, {"gateway_id": uuid4()}, {"created_by": uuid4()}, {"action": "unblock"}, {"mac": "11:22:33:44:55:66"}):
            with patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"role": "owner"}, {**self.command, **changes},
            ])):
                if changes:
                    with self.assertRaises(HTTPException) as caught:
                        commands.create_command(self.account, self.home, self.gateway, self.payload)
                    self.assertEqual(caught.exception.status_code, 409)
                else:
                    self.assertEqual(commands.create_command(
                        self.account, self.home, self.gateway, self.payload,
                    ), self.command)

    def test_delivery_rechecks_role_and_never_redelivers(self):
        for membership, delivered in (({"role": "admin"}, True), (None, False), ({"role": "member"}, False)):
            with patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"household_id": self.home}, self.command, membership, {"id": self.command_id},
            ])):
                result = commands.take_command(self.gateway, self.credential)
            self.assertEqual(result["command"] is not None, delivered)
            self.assertIn("status = 'queued'", self.db.execute.call_args_list[2].args[0])
            self.assertIn("revoked_at IS NULL", self.db.execute.call_args_list[0].args[0])
            self.assertIn("delivered" if delivered else "cancelled", self.db.execute.call_args.args[0])

    def test_expiry_is_rechecked_after_role_lookup_before_dispatch(self):
        with patch.object(commands, "connect", side_effect=lambda: self.connection([
            {"household_id": self.home}, self.command, {"role": "owner"}, None,
        ])):
            self.assertIsNone(commands.take_command(self.gateway, self.credential)["command"])
        self.assertIn("status = 'expired'", self.db.execute.call_args.args[0])

    def test_expiry_distinguishes_unexecuted_from_unconfirmed(self):
        db = MagicMock()
        commands._expire(db, self.gateway)
        query = db.execute.call_args.args[0]
        self.assertIn("THEN 'expired' ELSE 'unknown'", query)
        self.assertIn("clock_timestamp()", query)

    def test_result_is_scoped_idempotent_and_cannot_complete_queued_command(self):
        result = commands.CommandResult(success=True, result_code="applied")
        for row, expected in (
            (None, 404), ({"status": "queued", "result_code": None}, 409),
            ({"status": "expired", "result_code": None}, 409),
            ({"status": "failed", "result_code": "local_rejected"}, 409),
            ({"status": "succeeded", "result_code": "applied"}, None),
            ({"status": "delivered", "result_code": None}, None),
            ({"status": "unknown", "result_code": None}, None),
        ):
            with patch.object(commands, "connect", side_effect=lambda: self.connection([
                {"household_id": self.home}, row,
            ])):
                if expected:
                    with self.assertRaises(HTTPException) as caught:
                        commands.complete_command(self.gateway, self.credential, self.command_id, result)
                    self.assertEqual(caught.exception.status_code, expected)
                else:
                    self.assertEqual(commands.complete_command(
                        self.gateway, self.credential, self.command_id, result,
                    ), {"success": True, "status": "succeeded"})
            self.assertEqual(self.db.execute.call_args_list[1].args[1], (self.command_id, self.gateway))

    def test_timeout_is_unknown_not_success_or_definite_failure(self):
        with patch.object(commands, "connect", side_effect=lambda: self.connection([
            {"household_id": self.home}, {"status": "delivered", "result_code": None},
        ])):
            result = commands.complete_command(
                self.gateway, self.credential, self.command_id,
                commands.CommandResult(success=False, result_code="local_unreachable"),
            )
        self.assertEqual(result["status"], "unknown")

    def test_machine_requires_credential_not_user_token(self):
        for credential, rows, status in (("", [], 401), (self.credential, [None], 401),
                                          (self.credential, [{"household_id": None}], 409)):
            with patch.object(commands, "connect", side_effect=lambda: self.connection(rows)):
                with self.assertRaises(HTTPException) as caught:
                    commands.take_command(self.gateway, credential)
                self.assertEqual(caught.exception.status_code, status)

    def test_contracts_reject_arbitrary_actions_identity_and_false_success(self):
        for changes in ({"action": "shell"}, {"mac": "device; shutdown"}, {"account_id": str(uuid4())}):
            with self.assertRaises(ValidationError):
                commands.CommandInput(**{**self.payload.model_dump(), **changes})
        for result in (
            {"success": True, "result_code": "enforcement_failed"},
            {"success": False, "result_code": "applied"},
            {"success": "true", "result_code": "applied"},
        ):
            with self.assertRaises(ValidationError):
                commands.CommandResult(**result)

    def test_api_requires_account_for_create_and_machine_for_delivery(self):
        app = FastAPI()
        app.include_router(build_router("test-only-cloud-secret-32-characters"))
        client = TestClient(app)
        path = f"/cloud/households/{self.home}/gateways/{self.gateway}/commands"
        self.assertEqual(client.post(path, json=self.payload.model_dump(mode="json")).status_code, 401)
        self.assertEqual(client.post(f"/cloud/gateways/{self.gateway}/commands/next").status_code, 401)
        with (
            patch.object(accounts, "authenticate", return_value={"id": self.account}),
            patch.object(commands, "create_command", return_value=self.command) as create,
        ):
            response = client.post(path, json=self.payload.model_dump(mode="json"))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(create.call_args.args[:3], (self.account, self.home, self.gateway))


if __name__ == "__main__":
    unittest.main()
