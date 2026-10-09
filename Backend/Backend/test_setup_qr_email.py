import io
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import cloud_accounts as accounts
import cloud_account_security as security
from cloud_account_api import build_router


class SetupQrEmailTests(unittest.TestCase):
    @contextmanager
    def connection(self, row):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.return_value = row
        yield self.db

    def test_emails_png_to_verified_database_email_without_changing_pairing(self):
        account_id, gateway_id = uuid4(), uuid4()
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        with (
            patch.object(security, "connect", side_effect=lambda: self.connection({
                "email": "owner@example.invalid", "pairing_expires_at": expiry,
            })),
            patch.object(security, "_send_message") as send,
        ):
            result = security.email_setup_qr(account_id, gateway_id, " setup-secret ")
        self.assertTrue(result["success"])
        self.assertEqual(self.db.execute.call_count, 1)
        query, parameters = self.db.execute.call_args.args
        self.assertIn("g.household_id IS NULL", query)
        self.assertIn("g.revoked_at IS NULL", query)
        self.assertIn("g.pairing_expires_at > now()", query)
        self.assertIn("a.email_verified_at IS NOT NULL", query)
        self.assertEqual(parameters, (account_id, gateway_id, security.secret_hash("setup-secret")))
        message = send.call_args.args[0]
        self.assertEqual(message["To"], "owner@example.invalid")
        text = message.get_body(preferencelist=("plain",)).get_content()
        label = json.loads(text.split("Setup text:\n")[1])
        self.assertEqual(label, {
            "version": 1, "gateway_id": str(gateway_id), "pairing_code": "setup-secret",
        })
        self.assertIn(expiry.isoformat(), text)
        attachment = list(message.iter_attachments())[0]
        self.assertEqual(attachment.get_content_type(), "image/png")
        with Image.open(io.BytesIO(attachment.get_payload(decode=True))) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, image.height)
        self.assertNotIn("setup-secret", json.dumps(result))

    def test_invalid_expired_paired_or_revoked_label_does_not_email(self):
        with (
            patch.object(security, "connect", side_effect=lambda: self.connection(None)),
            patch.object(security, "_send_message") as send,
        ):
            with self.assertRaises(HTTPException) as failure:
                security.email_setup_qr(uuid4(), uuid4(), "invalid")
        self.assertEqual(failure.exception.status_code, 400)
        send.assert_not_called()

    def test_delivery_failure_is_not_success(self):
        with (
            patch.object(security, "connect", side_effect=lambda: self.connection({
                "email": "owner@example.invalid", "pairing_expires_at": datetime.now(timezone.utc),
            })),
            patch.object(security, "_send_message", side_effect=HTTPException(503, "Delivery failed.")),
        ):
            with self.assertRaises(HTTPException) as failure:
                security.email_setup_qr(uuid4(), uuid4(), "code")
        self.assertEqual(failure.exception.status_code, 503)


class SetupQrApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(build_router("test-only-session-secret-at-least-32-characters"))
        self.client = TestClient(app)
        self.account = {"id": uuid4(), "email_verified_at": "verified"}
        self.payload = {"gateway_id": str(uuid4()), "pairing_code": "test-code"}

    def test_requires_authentication_and_verification(self):
        self.assertEqual(self.client.post("/cloud/gateways/email-setup-qr", json=self.payload).status_code, 401)
        with (
            patch.object(accounts, "authenticate", return_value={**self.account, "email_verified_at": None}),
            patch.object(security, "email_setup_qr") as send,
        ):
            result = self.client.post("/cloud/gateways/email-setup-qr", json=self.payload)
        self.assertEqual(result.status_code, 403)
        send.assert_not_called()

    def test_session_identity_and_rate_limits_control_email(self):
        with (
            patch.object(accounts, "authenticate", return_value=self.account),
            patch.object(security, "limit") as limit,
            patch.object(security, "email_setup_qr", return_value={"success": True}) as send,
        ):
            result = self.client.post("/cloud/gateways/email-setup-qr", json=self.payload)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(limit.call_count, 2)
        send.assert_called_once_with(self.account["id"], UUID(self.payload["gateway_id"]), "test-code")

    def test_recipient_and_machine_credential_cannot_be_supplied(self):
        with patch.object(accounts, "authenticate", return_value=self.account):
            for extra in ({"email": "stranger@example.invalid"}, {"gateway_credential": "machine-secret"}):
                result = self.client.post("/cloud/gateways/email-setup-qr", json={**self.payload, **extra})
                self.assertEqual(result.status_code, 422)

    def test_throttling_prevents_delivery(self):
        with (
            patch.object(accounts, "authenticate", return_value=self.account),
            patch.object(security, "limit", side_effect=HTTPException(429, "Too many requests.")),
            patch.object(security, "email_setup_qr") as send,
        ):
            result = self.client.post("/cloud/gateways/email-setup-qr", json=self.payload)
        self.assertEqual(result.status_code, 429)
        send.assert_not_called()
