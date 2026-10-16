"""One-time, device-scoped pairing and purchase-bound recovery regressions."""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi import FastAPI

import cloud_accounts as accounts
import cloud_account_security as security
import cloud_gateways as gateways
from cloud_account_api import build_router


class RecoveryTests(unittest.TestCase):
    @contextmanager
    def connection(self, row):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.return_value = row
        yield self.db

    def test_replacement_rotates_only_verified_unpaired_purchase(self):
        account, gateway = uuid4(), uuid4()
        with patch.object(security, "connect", side_effect=lambda: self.connection(
            {"id": gateway, "email": "buyer@example.invalid"}
        )), patch.object(security, "email_setup_qr") as send:
            result = security.replace_setup_qr(account, " order-123 ")
        self.assertTrue(result["success"])
        query, params = self.db.execute.call_args_list[0].args
        self.assertEqual(params, (account, "order-123"))
        for required in ("a.email = p.purchaser_email", "a.email_verified_at IS NOT NULL",
                         "g.household_id IS NULL", "g.revoked_at IS NULL", "FOR UPDATE OF g"):
            self.assertIn(required, query)
        _, update = self.db.execute.call_args_list[1].args
        send.assert_called_once()
        self.assertEqual(send.call_args.args[:2], (account, gateway))
        self.assertEqual(update[0], security.secret_hash(send.call_args.args[2]))
        self.assertEqual(update[2], gateway)

    def test_missing_purchase_wrong_email_paired_or_revoked_never_sends(self):
        with patch.object(security, "connect", side_effect=lambda: self.connection(None)), \
                patch.object(security, "email_setup_qr") as send:
            with self.assertRaises(HTTPException):
                security.replace_setup_qr(uuid4(), "order-123")
        self.assertEqual(self.db.execute.call_count, 1)
        send.assert_not_called()

    def test_delivery_failure_is_explicit_and_does_not_restore_old_code(self):
        with patch.object(security, "connect", side_effect=lambda: self.connection(
            {"id": uuid4(), "email": "buyer@example.invalid"}
        )), patch.object(security, "email_setup_qr", side_effect=HTTPException(503, "Delivery failed")):
            with self.assertRaises(HTTPException) as failure:
                security.replace_setup_qr(uuid4(), "order-123")
        self.assertEqual(failure.exception.status_code, 503)
        self.assertEqual(self.db.execute.call_count, 2)

    def test_claim_is_device_scoped_consumes_secret_and_rejects_replay(self):
        account, gateway = uuid4(), uuid4()
        with patch.object(gateways, "connect", side_effect=lambda: self.connection(
            {"id": gateway, "name": "Pi"}
        )):
            gateways.pair_gateway(account, gateway, "secret", "Home")
        query, params = self.db.execute.call_args_list[0].args
        self.assertEqual(params, (gateway, gateways.secret_hash("secret")))
        self.assertIn("id = %s AND pairing_code_hash = %s", query)
        self.assertIn("FOR UPDATE", query)
        self.assertIn("household_id IS NULL", query)
        self.assertIn("pairing_code_hash = NULL", self.db.execute.call_args_list[-1].args[0])
        with patch.object(gateways, "connect", side_effect=lambda: self.connection(None)):
            with self.assertRaises(HTTPException):
                gateways.pair_gateway(account, gateway, "secret", "Home")
        self.assertEqual(self.db.execute.call_count, 1)

    def test_api_requires_verification_and_rejects_supplied_recipient(self):
        app = FastAPI()
        app.include_router(build_router("test-only-session-secret-at-least-32-characters"))
        client = TestClient(app)
        route = "/cloud/gateways/replace-setup-qr"
        self.assertEqual(client.post(route, json={"order_reference": "order"}).status_code, 401)
        with patch.object(accounts, "authenticate", return_value={
            "id": uuid4(), "email_verified_at": None,
        }):
            self.assertEqual(client.post(route, json={"order_reference": "order"}).status_code, 403)
        with patch.object(accounts, "authenticate", return_value={
            "id": uuid4(), "email_verified_at": "verified",
        }):
            self.assertEqual(client.post(route, json={
                "order_reference": "order", "email": "attacker@example.invalid",
            }).status_code, 422)

    def test_verified_api_uses_account_rate_limit_and_never_returns_code(self):
        app = FastAPI()
        secret = "test-only-session-secret-at-least-32-characters"
        app.include_router(build_router(secret))
        account_id = uuid4()
        with patch.object(accounts, "authenticate", return_value={
            "id": account_id, "email_verified_at": "verified",
        }), patch.object(security, "limit") as limit, \
                patch.object(security, "replace_setup_qr", return_value={
                    "success": True, "message": "Replacement sent.",
                }) as replace:
            client = TestClient(app)
            response = client.post("/cloud/gateways/replace-setup-qr", json={
                "order_reference": "order",
            })
            self.assertEqual(response.json(), {"success": True, "message": "Replacement sent."})
            limit.assert_called_once_with("replace-setup-qr:" + str(account_id), secret, 3, 900)
            replace.assert_called_once_with(account_id, "order")
            limit.side_effect = HTTPException(429, "Too many requests")
            self.assertEqual(client.post("/cloud/gateways/replace-setup-qr", json={
                "order_reference": "order",
            }).status_code, 429)
            self.assertEqual(replace.call_count, 1)


if __name__ == "__main__":
    unittest.main()
