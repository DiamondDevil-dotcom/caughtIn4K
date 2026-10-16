import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import cloud_accounts
import cloud_gateway_setup as setup
from cloud_account_api import build_router


class GatewaySetupTests(unittest.TestCase):
    def setUp(self):
        self.account, self.home, self.gateway, self.revision = (uuid4() for _ in range(4))
        self.key = Fernet.generate_key().decode("ascii")
        self.environment = patch.dict(os.environ, {
            "GHOST_CLOUD_SETUP_ENABLED": "true", "GHOST_CLOUD_SETUP_KEY": self.key,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.db = MagicMock()
        self.connection = patch.object(setup, "connect")
        self.connection.start().return_value.__enter__.return_value = self.db
        self.addCleanup(self.connection.stop)
        self.body = {"request_id": str(self.revision), "ssid": "Customer IoT", "password": "test-only-password"}
        self.report = setup.SetupReport(request_id=self.revision, checks=dict.fromkeys(setup.CHECKS, True))
        self.row = {
            "request_id": self.revision, "reported_request_id": self.revision,
            "encrypted_wifi": Fernet(self.key).encrypt(json.dumps({
                "ssid": self.body["ssid"], "password": self.body["password"],
            }).encode()).decode(),
            "received_at": datetime.now(timezone.utc), "checks": self.report.checks,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15), "error_code": None,
        }

    def rows(self, *rows):
        self.db.execute.return_value.fetchone.side_effect = rows

    def test_wifi_is_encrypted_and_not_echoed_then_consumed_and_ready(self):
        self.rows({"role": "owner"}, {"consumer_setup": True}, None, {"request_id": self.revision})
        result = setup.configure_wifi(self.account, self.home, self.gateway, self.body)
        self.assertEqual(result, {"request_id": str(self.revision)})
        params = self.db.execute.call_args.args[1]
        ciphertext = params[3]
        self.assertNotIn(self.body["password"], ciphertext)
        self.assertEqual(json.loads(Fernet(self.key).decrypt(ciphertext)), {
            "ssid": self.body["ssid"], "password": self.body["password"],
        })
        self.rows({"household_id": self.home, "consumer_setup": True}, self.row)
        self.assertIsNone(setup.exchange(self.gateway, "x" * 32, self.report)["configuration"])
        self.assertIn("encrypted_wifi = NULL", self.db.execute.call_args.args[0])
        self.rows({"role": "owner"}, {"consumer_setup": True}, self.row)
        status = setup.read_setup(self.account, self.home, self.gateway)
        self.assertTrue(status["ready"])
        self.assertNotIn("password", json.dumps(status))

    def test_only_authorized_owner_admin_can_change_new_consumer_gateway(self):
        for role, expected in ((None, 404), ({"role": "member"}, 403)):
            self.rows(role)
            with self.assertRaises(HTTPException) as caught:
                setup.configure_wifi(self.account, self.home, self.gateway, self.body)
            self.assertEqual(caught.exception.status_code, expected)
        self.rows({"role": "owner"}, {"consumer_setup": False})
        with self.assertRaises(HTTPException) as caught:
            setup.configure_wifi(self.account, self.home, self.gateway, self.body)
        self.assertEqual(caught.exception.status_code, 409)
        self.rows({"role": "admin"}, {"consumer_setup": True}, None, {"request_id": self.revision})
        setup.configure_wifi(self.account, self.home, self.gateway, self.body)

    def test_unpaired_gateway_gets_no_settings_and_invalid_machine_is_denied(self):
        self.rows({"household_id": None, "consumer_setup": True})
        result = setup.exchange(self.gateway, "x" * 32, self.report)
        self.assertEqual(result, {"paired": False, "configuration": None})
        for credential, rows in (("", []), ("x" * 32, [None])):
            self.rows(*rows)
            with self.assertRaises(HTTPException) as caught:
                setup.exchange(self.gateway, credential, self.report)
            self.assertEqual(caught.exception.status_code, 401)

    def test_pending_delivery_is_retryable_but_expired_delivery_is_scrubbed(self):
        pending = setup.SetupReport(checks=dict.fromkeys(setup.CHECKS, False))
        self.rows({"household_id": self.home, "consumer_setup": True}, self.row)
        result = setup.exchange(self.gateway, "x" * 32, pending)
        self.assertEqual(result["configuration"], self.body)
        expired = {**self.row, "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        self.rows({"household_id": self.home, "consumer_setup": True}, expired)
        self.assertIsNone(setup.exchange(self.gateway, "x" * 32, pending)["configuration"])
        self.assertIn("encrypted_wifi = NULL", self.db.execute.call_args.args[0])

    def test_offline_partial_old_revision_and_error_never_become_ready(self):
        for change in (
            {"received_at": datetime.now(timezone.utc) - timedelta(seconds=46)},
            {"checks": {**self.report.checks, "model": False}},
            {"reported_request_id": uuid4()}, {"error_code": "network_configuration_failed"},
            {"request_id": None}, {"checks": {}},
        ):
            self.rows({"role": "member"}, {"consumer_setup": True}, {**self.row, **change})
            self.assertFalse(setup.read_setup(self.account, self.home, self.gateway)["ready"])

    def test_retries_are_bound_to_same_payload_and_superseded_ids_are_rejected(self):
        # Obtain the actual HMAC from a new request, not a test-only alternate algorithm.
        self.rows({"role": "owner"}, {"consumer_setup": True}, None, {"request_id": self.revision})
        setup.configure_wifi(self.account, self.home, self.gateway, self.body)
        fingerprint = self.db.execute.call_args.args[1][2]
        current = {**self.row, "fingerprint": fingerprint}
        self.rows({"role": "owner"}, {"consumer_setup": True}, current)
        self.assertEqual(setup.configure_wifi(self.account, self.home, self.gateway, self.body)["request_id"], str(self.revision))
        self.rows({"role": "owner"}, {"consumer_setup": True}, current)
        with self.assertRaises(HTTPException):
            setup.configure_wifi(self.account, self.home, self.gateway, {**self.body, "password": "changed-password"})
        self.rows({"role": "owner"}, {"consumer_setup": True}, {**current, "request_id": uuid4()}, None)
        with self.assertRaises(HTTPException) as caught:
            setup.configure_wifi(self.account, self.home, self.gateway, self.body)
        self.assertEqual(caught.exception.status_code, 409)

    def test_invalid_secrets_control_characters_and_disabled_rollout_fail_closed(self):
        for changes in (
            {"ssid": "\n[connection]"}, {"ssid": "x" * 33}, {"password": "short"},
            {"password": "secret\ninjection"}, {"password": "é" * 8}, {"extra": True},
        ):
            with self.assertRaises(HTTPException) as caught:
                setup.configure_wifi(self.account, self.home, self.gateway, {**self.body, **changes})
            self.assertEqual(caught.exception.status_code, 400)
            self.assertNotIn(self.body["password"], str(caught.exception.detail))
        with patch.dict(os.environ, {"GHOST_CLOUD_SETUP_ENABLED": "false"}):
            with self.assertRaises(HTTPException) as caught:
                setup.read_setup(self.account, self.home, self.gateway)
            self.assertEqual(caught.exception.status_code, 503)
        with self.assertRaises(ValidationError):
            setup.SetupReport(checks={name: "true" for name in setup.CHECKS})

    def test_http_routes_require_verified_session_and_machine_auth(self):
        app = FastAPI()
        app.include_router(build_router("test-only-session-signing-secret-long", require_verified=True))
        with TestClient(app) as client:
            path = f"/cloud/households/{self.home}/gateways/{self.gateway}/setup"
            self.assertEqual(client.get(path).status_code, 401)
            with patch.object(cloud_accounts, "authenticate", return_value={
                "id": self.account, "email_verified_at": None,
            }):
                self.assertEqual(client.get(path, headers={"Authorization": "Bearer test"}).status_code, 403)
            machine_path = f"/cloud/gateways/{self.gateway}/setup/exchange"
            self.assertEqual(client.post(machine_path, json=self.report.model_dump(mode="json")).status_code, 401)


if __name__ == "__main__":
    unittest.main()
