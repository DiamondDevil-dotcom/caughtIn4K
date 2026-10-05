import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cloud_gateways as gateways
from cloud_account_api import build_router
import cloud_accounts as accounts


class GatewayPairingTests(unittest.TestCase):
    @contextmanager
    def connection(self, row=None):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.return_value = row
        self.db.execute.return_value.fetchall.return_value = []
        yield self.db

    def test_provisioning_stores_hashes_and_keeps_machine_secret_out_of_qr(self):
        expiry = datetime.now(timezone.utc) + timedelta(days=1)
        with patch.object(gateways, "connect", side_effect=self.connection):
            result = gateways.provision_gateway(" Kitchen Pi ", expiry)
        values = self.db.execute.call_args.args[1]
        self.assertEqual(values[1], "Kitchen Pi")
        self.assertEqual(values[2], gateways.secret_hash(result["gateway_credential"]))
        self.assertEqual(values[3], gateways.secret_hash(result["pairing_code"]))
        self.assertNotEqual(result["gateway_credential"], result["pairing_code"])
        self.assertNotIn(result["gateway_credential"], result["qr_payload"])
        self.assertEqual(json.loads(result["qr_payload"])["gateway_id"], result["gateway_id"])

    def test_invalid_expiry_does_not_register_a_gateway(self):
        with patch.object(gateways, "connect") as connect:
            for expiry in (datetime.now(), datetime.now(timezone.utc) - timedelta(seconds=1)):
                with self.assertRaises(ValueError):
                    gateways.provision_gateway("Pi", expiry)
        connect.assert_not_called()

    def test_pairing_is_locked_and_consumes_secret_in_same_transaction(self):
        account_id, gateway_id = uuid4(), uuid4()
        with patch.object(gateways, "connect", side_effect=lambda: self.connection({"id": gateway_id, "name": "Pi"})):
            result = gateways.pair_gateway(account_id, gateway_id, " private-code ", "My home")
        calls = self.db.execute.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertIn("FOR UPDATE", calls[0].args[0])
        self.assertIn("pairing_expires_at > now()", calls[0].args[0])
        self.assertIn("household_id IS NULL AND revoked_at IS NULL", calls[0].args[0])
        self.assertEqual(calls[0].args[1], (gateway_id, gateways.secret_hash("private-code")))
        self.assertEqual(calls[1].args[1][2], account_id)
        self.assertEqual(calls[2].args[1][1], account_id)
        self.assertIn("pairing_code_hash = NULL", calls[3].args[0])
        self.assertEqual(result["household_role"], "owner")
        self.assertNotIn("pairing_code", result)

    def test_invalid_expired_revoked_or_used_code_creates_no_household(self):
        with patch.object(gateways, "connect", side_effect=self.connection):
            with self.assertRaises(HTTPException) as caught:
                gateways.pair_gateway(uuid4(), uuid4(), "invalid", "Home")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.db.execute.call_count, 1)

    def test_empty_code_and_name_do_not_connect(self):
        with patch.object(gateways, "connect") as connect:
            for code, name in (("", "Home"), ("code", " ")):
                with self.assertRaises(HTTPException):
                    gateways.pair_gateway(uuid4(), uuid4(), code, name)
        connect.assert_not_called()

    def test_unrelated_account_cannot_list_or_infer_household(self):
        with patch.object(gateways, "connect", side_effect=self.connection):
            with self.assertRaises(HTTPException) as caught:
                gateways.list_gateways(uuid4(), uuid4())
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.db.execute.call_count, 1)

    def test_gateway_list_filters_authenticated_account_and_household(self):
        account_id, household_id = uuid4(), uuid4()
        with patch.object(gateways, "connect", side_effect=lambda: self.connection({"role": "member"})):
            self.assertEqual(gateways.list_gateways(account_id, household_id), [])
        query, values = self.db.execute.call_args.args
        self.assertEqual(values, (household_id, account_id))
        self.assertIn("m.account_id = %s", query)
        self.assertNotIn("credential_hash", query)
        self.assertNotIn("pairing_code_hash", query)


class GatewayPairingApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(build_router("test-only-secret-at-least-32-characters"))
        self.client = TestClient(app)
        self.account_id = uuid4()
        self.payload = {
            "gateway_id": str(uuid4()), "pairing_code": "private-code", "household_name": "My home",
        }

    def test_pairing_requires_sign_in(self):
        with patch.object(gateways, "pair_gateway") as pair:
            result = self.client.post("/cloud/gateways/pair", json=self.payload)
        self.assertEqual(result.status_code, 401)
        pair.assert_not_called()

    def test_owner_comes_from_verified_session(self):
        with (
            patch.object(accounts, "authenticate", return_value={"id": self.account_id}),
            patch.object(gateways, "pair_gateway", return_value={"success": True}) as pair,
        ):
            result = self.client.post("/cloud/gateways/pair", json=self.payload,
                                      headers={"Authorization": "Bearer test"})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(pair.call_args.args[0], self.account_id)

    def test_client_cannot_supply_owner_identity(self):
        with patch.object(accounts, "authenticate", return_value={"id": self.account_id}):
            result = self.client.post(
                "/cloud/gateways/pair", json={**self.payload, "account_id": str(uuid4())},
                headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(result.status_code, 422)

    def test_no_public_factory_registration_endpoint(self):
        response = self.client.post("/cloud/gateways/provision", json=self.payload)
        self.assertEqual(response.status_code, 404)

    def test_gateway_list_uses_session_not_query_identity(self):
        household_id = uuid4()
        with (
            patch.object(accounts, "authenticate", return_value={"id": self.account_id}),
            patch.object(gateways, "list_gateways", return_value=[]) as listing,
        ):
            result = self.client.get(
                f"/cloud/households/{household_id}/gateways?account_id={uuid4()}",
                headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(result.json(), {"gateways": []})
        listing.assert_called_once_with(self.account_id, household_id)


if __name__ == "__main__":
    unittest.main()
