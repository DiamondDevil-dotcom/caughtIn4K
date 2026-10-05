import time
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cloud_accounts as accounts
from cloud_account_api import build_router
from cloud_database import CloudDatabaseError
from gateway_auth import issue_session


class CloudAccountTests(unittest.TestCase):
    secret = "test-only-cloud-secret-with-at-least-32-characters"

    def setUp(self):
        self.account = {
            "id": uuid4(), "email": "owner@example.com",
            "name": "Owner", "session_version": 0,
        }

    @contextmanager
    def connection(self, account):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.return_value = account
        self.db.execute.return_value.fetchall.return_value = []
        yield self.db

    def test_signup_needs_no_pairing_code_and_creates_no_membership(self):
        with patch.object(accounts, "connect", side_effect=lambda: self.connection(self.account)):
            result = accounts.create_account(" Owner ", " OWNER@example.com ", "a-good-password")
        self.assertEqual(result["id"], self.account["id"])
        query, values = self.db.execute.call_args.args
        self.assertNotIn("household_members", query)
        self.assertEqual(values[1:3], ("owner@example.com", "Owner"))
        self.assertNotEqual(values[3], "a-good-password")
        self.assertEqual(values[-1], 600_000)

    def test_duplicate_account_is_explicit_error(self):
        with patch.object(accounts, "connect", side_effect=lambda: self.connection(None)):
            with self.assertRaises(HTTPException) as caught:
                accounts.create_account("Owner", "owner@example.com", "a-good-password")
        self.assertEqual(caught.exception.status_code, 409)

    def test_invalid_input_does_not_touch_database(self):
        with patch.object(accounts, "connect") as connect:
            for name, email, password in [
                ("", "owner@example.com", "a-good-password"),
                ("Owner", "not-an-email", "a-good-password"),
                ("Owner", "owner@example.com", "short"),
            ]:
                with self.subTest(email=email), self.assertRaises(HTTPException):
                    accounts.create_account(name, email, password)
        connect.assert_not_called()

    def test_login_supports_legacy_password_iteration_count(self):
        salt = bytes(range(16))
        row = {
            **self.account,
            "password_salt": salt.hex(),
            "password_algorithm": "pbkdf2_sha256",
            "password_iterations": 100_000,
            "password_hash": accounts.password_hash("old-password", salt, 100_000),
        }
        with patch.object(accounts, "connect", side_effect=lambda: self.connection(row)):
            self.assertEqual(accounts.login("owner@example.com", "old-password")["id"], row["id"])
            with self.assertRaises(HTTPException) as caught:
                accounts.login("owner@example.com", "wrong-password")
        self.assertEqual(caught.exception.status_code, 401)

    def test_missing_account_has_same_login_error(self):
        with patch.object(accounts, "connect", side_effect=lambda: self.connection(None)):
            with self.assertRaises(HTTPException) as caught:
                accounts.login("absent@example.com", "wrong-password")
        self.assertEqual(caught.exception.detail, "Invalid email or password.")

    def test_token_validated_against_current_database_identity(self):
        token = accounts.issue_token(self.account, self.secret)
        with patch.object(accounts, "connect", side_effect=lambda: self.connection(self.account)):
            result = accounts.authenticate("Bearer " + token, self.secret)
        self.assertEqual(result["id"], self.account["id"])
        self.assertEqual(self.db.execute.call_args.args[1], (self.account["id"],))

    def test_tampered_expired_and_legacy_tokens_rejected_before_database(self):
        token = accounts.issue_token(self.account, self.secret)
        with patch.object(accounts.time, "time", return_value=time.time() - 7200):
            expired = accounts.issue_token(self.account, self.secret)
        with patch.object(accounts, "connect") as connect:
            for value in ("", "Bearer " + token + "x", "Bearer " + expired,
                          "Bearer " + issue_session("owner@example.com")):
                with self.subTest(value=value[:10]), self.assertRaises(HTTPException) as caught:
                    accounts.authenticate(value, self.secret)
                self.assertEqual(caught.exception.status_code, 401)
        connect.assert_not_called()

    def test_deleted_and_revoked_accounts_rejected(self):
        token = accounts.issue_token(self.account, self.secret)
        for row in (None, {**self.account, "session_version": 1}):
            with patch.object(accounts, "connect", side_effect=lambda: self.connection(row)):
                with self.assertRaises(HTTPException) as caught:
                    accounts.authenticate("Bearer " + token, self.secret)
            self.assertEqual(caught.exception.status_code, 401)

    def test_households_are_scoped_by_authenticated_account_id(self):
        with patch.object(accounts, "connect", side_effect=lambda: self.connection(None)):
            self.assertEqual(accounts.memberships(self.account["id"]), [])
        query, values = self.db.execute.call_args.args
        self.assertIn("WHERE m.account_id = %s", query)
        self.assertEqual(values, (self.account["id"],))

    def test_public_account_never_returns_password_or_session_version(self):
        result = accounts.public_account({**self.account, "password_hash": "secret"})
        self.assertEqual(set(result), {"success", "account_id", "email", "name", "email_verified"})


class CloudApiTests(unittest.TestCase):
    def setUp(self):
        self.secret = CloudAccountTests.secret
        self.account = {
            "id": uuid4(), "email": "new@example.com", "name": "New user", "session_version": 0,
        }
        app = FastAPI()
        app.include_router(build_router(self.secret))
        self.client = TestClient(app)

    def test_cloud_router_requires_stable_secret(self):
        with self.assertRaises(ValueError):
            build_router("")

    def test_signup_returns_cloud_session_without_legacy_household_role(self):
        with patch.object(accounts, "create_account", return_value=self.account):
            response = self.client.post("/cloud/auth/signup", json={
                "email": "new@example.com", "password": "a-good-password", "name": "New user",
            })
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["access_token"].startswith("cloud-v1."))
        self.assertNotIn("household_role", response.json())

    def test_me_and_households_require_authentication(self):
        for path in ("/cloud/auth/me", "/cloud/households"):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_client_cannot_select_another_accounts_households(self):
        with (
            patch.object(accounts, "authenticate", return_value=self.account),
            patch.object(accounts, "memberships", return_value=[]) as memberships,
        ):
            response = self.client.get("/cloud/households?account_id=" + str(uuid4()),
                                       headers={"Authorization": "Bearer test-token"})
        self.assertEqual(response.json(), {"households": []})
        memberships.assert_called_once_with(self.account["id"])

    def test_database_failure_is_not_success_or_credentials(self):
        with patch.object(accounts, "login", side_effect=CloudDatabaseError("private connection")):
            response = self.client.post("/cloud/auth/login", json={
                "email": "new@example.com", "password": "a-good-password",
            })
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private connection", response.text)

    def test_cloud_api_cannot_route_to_legacy_devices(self):
        token = accounts.issue_token(self.account, self.secret)
        response = self.client.get("/cloud/devices", headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 404)

    def test_cloud_session_cannot_authorize_legacy_gateway(self):
        import app as backend

        token = accounts.issue_token(self.account, self.secret)
        with (
            patch.object(backend, "BACKEND_ROLE", "gateway"),
            patch.object(backend, "router_request") as router_request,
        ):
            response = TestClient(backend.app).get(
                "/devices", headers={"Authorization": "Bearer " + token},
            )
        self.assertEqual(response.status_code, 401)
        router_request.assert_not_called()

    def test_logout_all_uses_current_identity(self):
        with (
            patch.object(accounts, "authenticate", return_value=self.account),
            patch.object(accounts, "revoke_sessions") as revoke,
        ):
            response = self.client.post("/cloud/auth/logout-all",
                                        headers={"Authorization": "Bearer test-token"})
        self.assertEqual(response.json(), {"success": True})
        revoke.assert_called_once_with(self.account["id"])


if __name__ == "__main__":
    unittest.main()
