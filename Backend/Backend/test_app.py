import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app as backend
from gateway_auth import issue_session


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GHOST_ALLOWED_EMAILS": "owner@example.com",
            "GHOST_ROUTER_TOKEN": "test-only-router-token",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.role = patch.object(backend, "BACKEND_ROLE", "gateway")
        self.role.start()
        self.addCleanup(self.role.stop)
        self.client = TestClient(backend.app)
        self.headers = {"Authorization": f"Bearer {issue_session('owner@example.com')}"}
        self.device = {
            "mac": "aa:bb:cc:dd:ee:ff", "name": "Test phone", "status": "SAFE",
            "attack_probability": 10, "blocked": False,
        }

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_cloud_staging_requires_separate_private_access(self):
        staging_token = "test-only-staging-token-at-least-32-characters"
        with (
            patch.object(backend, "CLOUD_ACCOUNTS_ENABLED", True),
            patch.dict(os.environ, {"GHOST_CLOUD_STAGING_TOKEN": staging_token}),
            patch.object(backend, "router_request") as router,
        ):
            for headers in ({}, self.headers, {"X-Cloud-Staging-Token": "wrong"}):
                result = self.client.get("/cloud/unknown", headers=headers)
                self.assertEqual(result.status_code, 401)
            allowed = self.client.get(
                "/cloud/unknown", headers={"X-Cloud-Staging-Token": staging_token},
            )
            self.assertEqual(allowed.status_code, 404)
            self.assertEqual(self.client.get("/health").status_code, 200)
        router.assert_not_called()

    def test_cloud_staging_fails_closed_when_secret_missing(self):
        with (
            patch.object(backend, "CLOUD_ACCOUNTS_ENABLED", True),
            patch.dict(os.environ, {"GHOST_CLOUD_STAGING_TOKEN": ""}),
        ):
            self.assertEqual(self.client.get("/cloud/unknown").status_code, 401)

    def test_devices_require_sign_in(self):
        self.assertEqual(self.client.get("/devices").status_code, 401)

    def test_live_prediction_rejects_accounts_without_device_access(self):
        with patch.object(
            backend, "router_request",
            side_effect=backend.HTTPException(status_code=403, detail="Household access required."),
        ):
            response = self.client.post(
                "/live-predict",
                json={"device_id": "aa:bb:cc:dd:ee:ff", "features": {"HTTP": 1.0}},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 403)

    def test_session_cannot_be_tampered_with(self):
        token = self.headers["Authorization"] + "tampered"
        self.assertEqual(self.client.get("/devices", headers={"Authorization": token}).status_code, 401)

    def test_devices_keep_pi_and_website_fields(self):
        with patch.object(backend, "router_request", return_value={"devices": [self.device]}):
            response = self.client.get("/devices", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        device = response.json()["devices"][0]
        self.assertEqual(device["mac"], device["device_id"])
        self.assertEqual(device["name"], "Test phone")

    def test_router_offline_is_not_an_empty_list(self):
        with patch("app.httpx.request", side_effect=httpx.ConnectError("offline")):
            response = self.client.get("/devices", headers=self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("devices", response.json())

    def test_invalid_upstream_json_is_reported(self):
        response = httpx.Response(200, text="<html>tunnel unavailable</html>",
                                 request=httpx.Request("GET", "https://pi.example/devices"))
        with patch("app.httpx.request", return_value=response):
            result = self.client.get("/devices", headers=self.headers)
        self.assertEqual(result.status_code, 502)

    def test_invalid_device_payload_is_not_empty_success(self):
        for payload in ([], {}, {"devices": "not a list"}, {"devices": [1]}):
            with self.subTest(payload=payload):
                response = httpx.Response(200, json=payload,
                                         request=httpx.Request("GET", "https://pi.example/devices"))
                with patch("app.httpx.request", return_value=response):
                    result = self.client.get("/devices", headers=self.headers)
                self.assertEqual(result.status_code, 502)

    def test_pi_errors_are_preserved(self):
        response = httpx.Response(503, json={"detail": "Pi checkpoint missing"},
                                 request=httpx.Request("GET", "https://pi.example/federated-status"))
        with patch("app.httpx.request", return_value=response):
            result = self.client.get("/federated-status", headers=self.headers)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()["detail"], "Pi checkpoint missing")

    def test_auth_proxies_and_issues_session(self):
        account = {"success": True, "email": "owner@example.com", "name": "Owner"}
        with patch.object(backend, "router_request", return_value=account):
            response = self.client.post("/auth/login", json={"email": "owner@example.com", "password": "test"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_rejected_website_login_does_not_succeed(self):
        with patch.object(backend, "router_request", return_value={"success": False, "error": "Wrong password"}):
            response = self.client.post("/login", json={"username": "owner@example.com", "password": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_unapproved_owner_is_denied(self):
        with patch.object(backend, "router_request", return_value={
            "success": False,
            "error": "A valid household invitation is required.",
        }) as router:
            response = self.client.post(
                "/auth/signup",
                json={"name": "Stranger", "email": "stranger@example.com", "password": "test-pass"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertNotIn("access_token", response.json())
        router.assert_called_once()

    def test_auth_changes_events_and_telemetry_proxy(self):
        for method, path, body, upstream in (
            ("POST", "/auth/change-password", {"email": "owner@example.com"}, "/auth/change-password"),
            ("POST", "/telemetry", {"features": [1] * 14}, "/telemetry"),
            ("GET", "/events", None, "/events"),
        ):
            with self.subTest(path=path), patch.object(backend, "router_request", return_value={"success": True}) as router:
                response = self.client.request(method, path, json=body, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(router.call_args.args[:2], (method, upstream))

    def test_authenticated_identity_is_forwarded_to_pi(self):
        upstream = httpx.Response(
            200,
            json={"devices": []},
            request=httpx.Request("GET", "https://pi.example/devices"),
        )
        with patch("app.httpx.request", return_value=upstream) as request:
            response = self.client.get("/devices", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            request.call_args.kwargs["headers"]["X-Gateway-User"],
            "owner@example.com",
        )

    def test_change_password_uses_signed_in_identity_not_client_email(self):
        with patch.object(backend, "router_request", return_value={"success": True}) as router:
            response = self.client.post(
                "/auth/change-password",
                json={
                    "email": "someone-else@example.com",
                    "current_password": "current",
                    "new_password": "replacement",
                },
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(router.call_args.kwargs["json"]["email"], "owner@example.com")

    def test_training_aliases_use_pi_not_local_simulation(self):
        for path in ("/federated/start", "/federated/train"):
            with self.subTest(path=path), patch.object(backend, "router_request", return_value={"success": True}) as router:
                self.assertEqual(self.client.post(path, headers=self.headers).status_code, 200)
                router.assert_called_once_with("POST", "/federated/start", timeout=30)

    def test_gateway_cannot_impersonate_coordinator(self):
        self.assertEqual(self.client.get("/federated-training/status", headers=self.headers).status_code, 409)

    def test_status_is_pi_status(self):
        status = {"model_source": "raspberry-pi", "training": {"state": "unavailable"}, "federated_round": 3}
        with patch.object(backend, "router_request", return_value=status):
            response = self.client.get("/federated-status", headers=self.headers)
        self.assertEqual(response.json(), status)

    def test_failed_block_is_not_success(self):
        with patch.object(backend, "router_request", return_value={"success": False, "detail": "Firewall unavailable"}):
            response = self.client.post("/devices/aa:bb:cc:dd:ee:ff/block", headers=self.headers)
        self.assertEqual(response.status_code, 502)

    def test_coordinator_role_starts_real_controller(self):
        with patch.object(backend, "BACKEND_ROLE", "coordinator"), \
             patch.object(backend.COORDINATOR, "start", return_value={"success": True}) as start:
            response = self.client.post("/federated/train", headers={"X-Gateway-Token": "test-only-router-token"})
        self.assertEqual(response.status_code, 200)
        start.assert_called_once()

    def test_coordinator_requires_private_token(self):
        with patch.object(backend, "BACKEND_ROLE", "coordinator"):
            self.assertEqual(self.client.post("/federated/train").status_code, 401)

    def test_detect_uses_live_mac(self):
        with patch.object(backend, "router_request", return_value={"devices": [self.device]}):
            response = self.client.get("/detect/aa:bb:cc:dd:ee:ff", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["label"], "Benign")

    def test_private_token_is_forwarded(self):
        upstream = httpx.Response(200, json={"devices": []},
                                  request=httpx.Request("GET", "https://pi.example/devices"))
        with patch("app.httpx.request", return_value=upstream) as request:
            self.client.get("/devices", headers=self.headers)
        self.assertEqual(request.call_args.kwargs["headers"]["X-Gateway-Token"], "test-only-router-token")

    def test_debug_uses_authenticated_proxy_without_device_contents(self):
        upstream = httpx.Response(200, json={"devices": [self.device]},
                                  request=httpx.Request("GET", "https://pi.example/devices"))
        with patch("app.httpx.request", return_value=upstream) as request:
            response = self.client.get("/debug/router", headers=self.headers)
        self.assertEqual(response.json()["device_count"], 1)
        self.assertNotIn("content_preview", response.json())
        self.assertEqual(request.call_args.kwargs["headers"]["X-Gateway-Token"], "test-only-router-token")


if __name__ == "__main__":
    unittest.main()
