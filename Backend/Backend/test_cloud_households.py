import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cloud_accounts as accounts
import cloud_households as households
from cloud_account_api import build_router
from cloud_gateways import secret_hash


class HouseholdInviteTests(unittest.TestCase):
    @contextmanager
    def connection(self, rows):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.side_effect = rows
        yield self.db

    def test_invite_stores_only_hash_and_scopes_inviter(self):
        owner, home = uuid4(), uuid4()
        expiry = datetime.now(timezone.utc)
        with patch.object(households, "connect", side_effect=lambda: self.connection([
            {"role": "owner"}, None, {"expires_at": expiry},
        ])):
            result = households.create_invite(owner, home, " MEMBER@example.com ", "member")
        calls = self.db.execute.call_args_list
        self.assertEqual(calls[0].args[1], (home, owner))
        self.assertIn("FOR SHARE", calls[0].args[0])
        self.assertEqual(calls[-1].args[1], (
            secret_hash(result["invite_code"]), home, "member@example.com", "member", owner,
        ))
        self.assertEqual(result["expires_at"], expiry)

    def test_admin_can_invite_member_but_not_admin(self):
        for role, allowed in (("member", True), ("admin", False)):
            with patch.object(households, "connect", side_effect=lambda: self.connection([
                {"role": "admin"}, None, {"expires_at": datetime.now(timezone.utc)},
            ])):
                if allowed:
                    households.create_invite(uuid4(), uuid4(), "a@example.com", role)
                else:
                    with self.assertRaises(HTTPException) as caught:
                        households.create_invite(uuid4(), uuid4(), "a@example.com", role)
                    self.assertEqual(caught.exception.status_code, 403)

    def test_member_and_outsider_cannot_invite(self):
        for inviter, status in (({"role": "member"}, 403), (None, 404)):
            with patch.object(households, "connect", side_effect=lambda: self.connection([inviter])):
                with self.assertRaises(HTTPException) as caught:
                    households.create_invite(uuid4(), uuid4(), "a@example.com", "member")
            self.assertEqual(caught.exception.status_code, status)
            self.assertEqual(self.db.execute.call_count, 1)

    def test_cannot_invite_owner_or_existing_member(self):
        with patch.object(households, "connect") as connect:
            with self.assertRaises(HTTPException):
                households.create_invite(uuid4(), uuid4(), "a@example.com", "owner")
        connect.assert_not_called()
        with patch.object(households, "connect", side_effect=lambda: self.connection([
            {"role": "owner"}, {"exists": 1},
        ])):
            with self.assertRaises(HTTPException) as caught:
                households.create_invite(uuid4(), uuid4(), "a@example.com", "member")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.execute.call_count, 2)

    def test_accept_locks_invite_binds_email_and_consumes_atomically(self):
        home, account, inviter = uuid4(), uuid4(), uuid4()
        with patch.object(households, "connect", side_effect=lambda: self.connection([
            {"household_id": home, "role": "member", "created_by": inviter},
            {"role": "owner"}, {"role": "member"},
        ])):
            result = households.accept_invite(account, " secret ")
        calls = self.db.execute.call_args_list
        self.assertIn("a.id = %s FOR UPDATE OF i", calls[0].args[0])
        self.assertIn("a.email = i.email", calls[0].args[0])
        self.assertIn("i.expires_at > now()", calls[0].args[0])
        self.assertEqual(calls[0].args[1], (secret_hash("secret"), account))
        self.assertEqual(calls[1].args[1], (home, inviter))
        self.assertIn("DO NOTHING", calls[2].args[0])
        self.assertIn("DELETE", calls[-1].args[0])
        self.assertEqual(result["household_role"], "member")

    def test_wrong_account_expired_or_reused_code_is_generic_error(self):
        with patch.object(households, "connect", side_effect=lambda: self.connection([None])):
            with self.assertRaises(HTTPException) as caught:
                households.accept_invite(uuid4(), "invalid")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.db.execute.call_count, 1)

    def test_demoted_or_removed_inviter_cannot_grant_access(self):
        for inviter in (None, {"role": "member"}, {"role": "admin"}):
            with patch.object(households, "connect", side_effect=lambda: self.connection([
                {"household_id": uuid4(), "created_by": uuid4(), "role": "admin"}, inviter,
            ])):
                with self.assertRaises(HTTPException):
                    households.accept_invite(uuid4(), "code")
            self.assertEqual(self.db.execute.call_count, 2)

    def test_existing_membership_cannot_be_overwritten(self):
        with patch.object(households, "connect", side_effect=lambda: self.connection([
            {"household_id": uuid4(), "created_by": uuid4(), "role": "admin"},
            {"role": "owner"}, None,
        ])):
            with self.assertRaises(HTTPException) as caught:
                households.accept_invite(uuid4(), "code")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.execute.call_count, 3)


class HouseholdInviteApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(build_router("test-secret-with-at-least-32-characters"))
        self.client = TestClient(app)
        self.account_id, self.home = uuid4(), uuid4()
        self.headers = {"Authorization": "Bearer test"}

    def test_inviting_and_accepting_require_authentication(self):
        for path, data in (
            (f"/cloud/households/{self.home}/invites", {"email": "a@example.com"}),
            ("/cloud/household-invites/accept", {"invite_code": "code"}),
        ):
            self.assertEqual(self.client.post(path, json=data).status_code, 401)

    def test_inviter_identity_is_not_client_controlled(self):
        with (
            patch.object(accounts, "authenticate", return_value={"id": self.account_id}),
            patch.object(households, "create_invite", return_value={"success": True}) as create,
        ):
            response = self.client.post(
                f"/cloud/households/{self.home}/invites",
                json={"email": "a@example.com", "role": "member"}, headers=self.headers,
            )
        self.assertEqual(response.status_code, 201)
        create.assert_called_once_with(self.account_id, self.home, "a@example.com", "member")

    def test_acceptance_identity_comes_from_session_only(self):
        with (
            patch.object(accounts, "authenticate", return_value={"id": self.account_id}),
            patch.object(households, "accept_invite", return_value={"success": True}) as accept,
        ):
            response = self.client.post("/cloud/household-invites/accept",
                                        json={"invite_code": "code"}, headers=self.headers)
            invalid = self.client.post(
                "/cloud/household-invites/accept",
                json={"invite_code": "code", "email": "victim@example.com"}, headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(invalid.status_code, 422)
        accept.assert_called_once_with(self.account_id, "code")


if __name__ == "__main__":
    unittest.main()
