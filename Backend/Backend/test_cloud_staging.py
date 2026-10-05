import importlib
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class CloudStagingTests(unittest.TestCase):
    def setUp(self):
        self.token = "test-private-staging-token-at-least-32"
        self.env = patch.dict(os.environ, {
            "GHOST_CLOUD_STAGING_TOKEN": self.token,
            "GHOST_CLOUD_SESSION_SECRET": "test-cloud-session-secret-at-least-32",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.module = importlib.import_module("cloud_staging_app")
        self.client = TestClient(self.module.create_app())

    def test_health_is_public_and_needs_no_database_or_model(self):
        with patch("cloud_database.connect", side_effect=AssertionError("Unexpected database access")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_private_access_required_even_for_signup(self):
        response = self.client.post("/cloud/auth/signup", json={
            "name": "Test", "email": "test@example.com", "password": "test-password",
        })
        self.assertEqual(response.status_code, 401)

    def test_staging_access_does_not_replace_account_session(self):
        response = self.client.get("/cloud/households",
                                   headers={"X-Cloud-Staging-Token": self.token})
        self.assertEqual(response.status_code, 401)

    def test_legacy_and_coordinator_routes_not_exposed(self):
        for path in ("/devices", "/auth/login", "/federated/train", "/docs", "/openapi.json"):
            response = self.client.get(path, headers={"X-Cloud-Staging-Token": self.token})
            self.assertEqual(response.status_code, 404)

    def test_missing_secret_fails_startup(self):
        with patch.dict(os.environ, {"GHOST_CLOUD_STAGING_TOKEN": ""}):
            with self.assertRaises(ValueError):
                self.module.create_app()


if __name__ == "__main__":
    unittest.main()
