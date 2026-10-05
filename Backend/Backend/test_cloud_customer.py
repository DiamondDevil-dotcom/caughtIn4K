import importlib
import os
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

import cloud_accounts as accounts
import cloud_account_security as security
from cloud_database import CloudDatabaseError


class CustomerAppTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GHOST_CLOUD_CUSTOMER_ENABLED": "true",
            "GHOST_CLOUD_SESSION_SECRET": "test-private-session-secret-32-characters",
            "GHOST_SMTP_HOST": "smtp.example.invalid",
            "GHOST_SMTP_PORT": "587",
            "GHOST_SMTP_FROM": "test@example.invalid",
            "GHOST_CLOUD_WEB_ORIGINS": "https://home.example.invalid",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.module = importlib.import_module("cloud_customer_app")
        self.client = TestClient(self.module.create_app())
        self.limit = patch.object(self.module, "limit")
        self.limit_mock = self.limit.start()
        self.addCleanup(self.limit.stop)

    def test_health_is_public_and_needs_no_throttling_storage(self):
        result = self.client.get("/health")
        self.assertEqual(result.status_code, 200)
        self.limit_mock.assert_not_called()

    def test_login_uses_account_password_without_staging_secret(self):
        with patch.object(accounts, "login", return_value={
            "id": uuid4(), "name": "Owner", "email": "owner@example.invalid",
            "session_version": 0, "email_verified_at": "verified",
        }):
            result = self.client.post("/cloud/auth/login", json={
                "email": "owner@example.invalid", "password": "test-password",
            })
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["access_token"].startswith("cloud-v1."))
        self.assertTrue(result.json()["email_verified"])
        self.assertEqual(self.limit_mock.call_count, 2)

    def test_account_authentication_is_still_required(self):
        self.assertEqual(self.client.get("/cloud/households").status_code, 401)

    def test_unverified_account_cannot_pair_or_access_household(self):
        account = {"id": uuid4(), "email_verified_at": None}
        with patch.object(accounts, "authenticate", return_value=account):
            self.assertEqual(self.client.get("/cloud/households").status_code, 403)
            self.assertEqual(self.client.post("/cloud/gateways/pair", json={
                "gateway_id": str(uuid4()), "pairing_code": "test", "household_name": "Home",
            }).status_code, 403)

    def test_account_can_request_verification_before_verified(self):
        account = {"id": uuid4(), "email_verified_at": None}
        with (
            patch.object(accounts, "authenticate", return_value=account),
            patch.object(security, "limit"),
            patch.object(security, "send_verification", return_value={"success": True}),
        ):
            self.assertEqual(self.client.post("/cloud/auth/request-verification").status_code, 200)

    def test_throttle_failures_are_explicit_and_cors_visible(self):
        for failure, expected in (
            (HTTPException(429, "Too many requests.", headers={"Retry-After": "60"}), 429),
            (CloudDatabaseError("private diagnostic"), 503),
        ):
            self.limit_mock.side_effect = failure
            result = self.client.get("/cloud/households", headers={"Origin": "https://home.example.invalid"})
            self.assertEqual(result.status_code, expected)
            self.assertEqual(result.headers["access-control-allow-origin"], "https://home.example.invalid")
            self.assertNotIn("private diagnostic", result.text)

    def test_startup_requires_explicit_enable_mail_and_exact_origins(self):
        for changes in (
            {"GHOST_CLOUD_CUSTOMER_ENABLED": "false"},
            {"GHOST_SMTP_HOST": ""},
            {"GHOST_CLOUD_WEB_ORIGINS": "*"},
            {"GHOST_CLOUD_WEB_ORIGINS": "https://*.example.invalid"},
            {"GHOST_CLOUD_WEB_ORIGINS": "http://example.invalid"},
        ):
            with patch.dict(os.environ, changes), self.assertRaises(ValueError):
                self.module.create_app()


class SecurityTests(unittest.TestCase):
    @contextmanager
    def connection(self, rows):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.side_effect = rows
        yield self.db

    def test_limits_are_shared_atomic_hashed_and_committed_before_rejection(self):
        with patch.object(security, "connect", side_effect=lambda: self.connection([{"attempts": 11}])):
            with self.assertRaises(HTTPException) as caught:
                security.limit("owner@example.invalid", "test-secret", 10, 900)
        self.assertEqual(caught.exception.status_code, 429)
        query, values = self.db.execute.call_args_list[0].args
        self.assertIn("ON CONFLICT", query)
        self.assertEqual(len(values[0]), 64)
        self.assertNotIn("owner@example.invalid", values[0])

    def test_bad_codes_increment_attempts_and_do_not_rollback_on_error(self):
        home = uuid4()
        with patch.object(security, "connect", side_effect=lambda: self.connection([
            {"live": True, "attempts": 0, "token_hash": "0" * 64},
        ])):
            with self.assertRaises(HTTPException):
                security.verify_email(home, "wrong-code")
        self.assertIn("attempts = attempts + 1", self.db.execute.call_args.args[0])

    def test_expired_or_exhausted_codes_never_verify(self):
        for live, attempts in ((False, 0), (True, 5)):
            with patch.object(security, "connect", side_effect=lambda: self.connection([
                {"live": live, "attempts": attempts, "token_hash": security.secret_hash("code")},
            ])):
                with self.assertRaises(HTTPException):
                    security.verify_email(uuid4(), "code")
            self.assertEqual(self.db.execute.call_count, 2)

    def test_valid_reset_is_single_use_and_revokes_sessions(self):
        with (
            patch.object(security, "connect", side_effect=lambda: self.connection([
                {"live": True, "attempts": 0, "token_hash": security.secret_hash("code")},
            ])),
            patch.object(accounts, "password_hash", return_value="digest"),
        ):
            self.assertTrue(security._consume(uuid4(), "code", verification=False, password="new-password")["success"])
        queries = [call.args[0] for call in self.db.execute.call_args_list]
        self.assertTrue(any("session_version = session_version + 1" in query for query in queries))
        self.assertTrue(any("DELETE FROM caughtin4k.password_reset_tokens" in query for query in queries))

    def test_reset_does_not_disclose_account_existence_and_missing_accounts_still_email(self):
        for row in (None, {"id": uuid4()}):
            with (
                patch.object(security, "connect", side_effect=lambda: self.connection([row])),
                patch.object(security, "send_code") as send,
            ):
                result = security.request_reset("owner@example.invalid")
            self.assertEqual(result, {"success": True, "message": "If the account exists, a reset code was sent."})
            send.assert_called_once()

    def test_mail_uses_starttls_and_never_echoes_smtp_errors(self):
        with (
            patch.object(security, "mail_settings", return_value=("smtp.example.invalid", 587, "user", "secret", "sender@example.invalid")),
            patch.object(security.smtplib, "SMTP") as smtp,
        ):
            security.send_code("owner@example.invalid", "code", "password reset")
        smtp.return_value.starttls.assert_called_once()
        smtp.return_value.login.assert_called_once_with("user", "secret")
        with patch.object(security, "mail_settings", side_effect=ValueError("private secret")):
            with self.assertRaises(HTTPException) as caught:
                security.send_code("owner@example.invalid", "code", "password reset")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("private secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
