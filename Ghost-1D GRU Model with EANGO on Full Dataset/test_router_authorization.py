import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import router_ids_agent as router


class PiAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_patch = patch.object(
            router.storage, "DB_PATH", str(Path(self.temp_dir.name) / "router_ids.db")
        )
        self.database_patch.start()
        self.environment_patch = patch.dict(
            os.environ,
            {
                "GHOST_ROUTER_TOKEN": "private-gateway-test-token",
                "GHOST_GATEWAY_PAIRING_CODE": "one-time-test-setup-code",
            },
        )
        self.environment_patch.start()
        router.storage.init_db()
        created, error = router.storage.create_account(
            "Owner",
            "owner@example.com",
            "correct-password",
            "one-time-test-setup-code",
        )
        self.assertTrue(created, error)
        self.member_headers = {
            "X-Gateway-Token": "private-gateway-test-token",
            "X-Gateway-User": "owner@example.com",
        }
        self.client = TestClient(router.app)

    def tearDown(self):
        self.environment_patch.stop()
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_device_and_event_routes_require_valid_household_identity(self):
        private_headers = {"X-Gateway-Token": "private-gateway-test-token"}
        self.assertEqual(self.client.get("/devices", headers=private_headers).status_code, 403)
        self.assertEqual(
            self.client.get(
                "/devices",
                headers={
                    **private_headers,
                    "X-Gateway-User": "uninvited@example.com",
                },
            ).status_code,
            403,
        )
        for path in ("/events", "/federated-status"):
            self.assertEqual(
                self.client.get(
                    path,
                    headers={
                        **private_headers,
                        "X-Gateway-User": "uninvited@example.com",
                    },
                ).status_code,
                403,
            )
        self.assertEqual(
            self.client.post(
                "/devices/aa:bb:cc:dd:ee:ff/block",
                headers={
                    **private_headers,
                    "X-Gateway-User": "uninvited@example.com",
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/devices", headers=self.member_headers).status_code, 200
        )
        self.assertEqual(
            self.client.get("/events", headers=self.member_headers).status_code, 200
        )

    def test_private_token_is_required_even_before_household_checks(self):
        self.assertEqual(self.client.get("/devices").status_code, 401)
        with patch.dict(os.environ, {"GHOST_ROUTER_TOKEN": ""}):
            self.assertEqual(self.client.get("/devices").status_code, 503)

    def test_coordinator_client_routes_require_private_token_not_user_session(self):
        payload = {"server_address": "192.168.50.198:8081"}
        self.assertEqual(
            self.client.post("/federated/start-client", json=payload).status_code, 401
        )
        with patch.object(router, "_start_pi_federated_client", return_value={"success": True}):
            response = self.client.post(
                "/federated/start-client",
                json=payload,
                headers={"X-Gateway-Token": "private-gateway-test-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.post("/federated/stop-client").status_code, 401
        )
        with patch.object(router, "_stop_pi_federated_client", return_value={"success": True}):
            response = self.client.post(
                "/federated/stop-client",
                headers={"X-Gateway-Token": "private-gateway-test-token"},
            )
        self.assertEqual(response.status_code, 200)

    def test_member_cannot_register_devices_or_start_training(self):
        ok, error, invite = router.storage.create_invite(
            "owner@example.com", "member@example.com", "member"
        )
        self.assertTrue(ok, error)
        created, error = router.storage.create_account(
            "Member",
            "member@example.com",
            "correct-password",
            invite["invite_code"],
        )
        self.assertTrue(created, error)
        member_headers = {
            "X-Gateway-Token": "private-gateway-test-token",
            "X-Gateway-User": "member@example.com",
        }
        self.assertEqual(
            self.client.post(
                "/devices/register",
                json={
                    "name": "Unapproved device",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "ip_address": "192.168.4.20",
                },
                headers=member_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/federated/start", headers=member_headers).status_code,
            403,
        )

    def test_guessed_unregistered_device_cannot_be_blocked(self):
        response = self.client.post(
            "/devices/aa:bb:cc:dd:ee:ff/block", headers=self.member_headers
        )
        self.assertEqual(response.status_code, 404)

    def test_password_reset_email_failure_is_reported(self):
        with patch.object(router, "send_reset_email", return_value=False):
            response = self.client.post(
                "/auth/request-password-reset",
                json={"email": "owner@example.com"},
                headers={"X-Gateway-Token": "private-gateway-test-token"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("email delivery", response.json()["detail"].lower())
        self.assertEqual(
            self.client.post(
                "/auth/reset-password",
                json={
                    "email": "owner@example.com",
                    "token": "000000",
                    "new_password": "replacement-password",
                },
                headers={"X-Gateway-Token": "private-gateway-test-token"},
            ).json()["success"],
            False,
        )

    def test_password_reset_success_uses_the_email_code_delivery(self):
        with patch.object(router, "send_reset_email", return_value=True) as send_email:
            response = self.client.post(
                "/auth/request-password-reset",
                json={"email": "owner@example.com"},
                headers={"X-Gateway-Token": "private-gateway-test-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(send_email.call_args.args[0], "owner@example.com")
        self.assertRegex(send_email.call_args.args[1], r"^\d{6}$")


if __name__ == "__main__":
    unittest.main()
