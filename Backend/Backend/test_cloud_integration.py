"""Opt-in live PostgreSQL verification using only uniquely named test records."""

import os
import secrets
import hashlib
import hmac
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException

import cloud_accounts as accounts
import cloud_gateways as gateways
import cloud_households as households
import cloud_monitoring as monitoring
import cloud_commands as commands
import cloud_account_security as security
from cloud_database import check_schema, connect, read_database_url


@unittest.skipUnless(
    os.getenv("GHOST_RUN_CLOUD_INTEGRATION") == "true",
    "Live cloud integration is explicit and opt-in.",
)
class CloudIntegrationTests(unittest.TestCase):
    def test_customer_email_proof_recovery_revocation_and_shared_limits(self):
        check_schema()
        account_id = None
        limit_key = "integration:" + uuid4().hex
        secret = secrets.token_urlsafe(32)
        key_hash = hmac.new(secret.encode(), limit_key.encode(), hashlib.sha256).hexdigest()
        password = secrets.token_urlsafe(24)
        try:
            account = accounts.create_account("Customer integration", f"test-{uuid4().hex}@example.invalid", password)
            account_id = account["id"]
            self.assertIsNone(account["email_verified_at"])
            token = accounts.issue_token(account, secret)
            with patch.object(security, "send_code") as mail:
                security.send_verification(account_id)
                code = mail.call_args.args[1]
            with self.assertRaises(HTTPException):
                security.verify_email(account_id, "wrong")
            with connect() as connection:
                row = connection.execute(
                    "SELECT attempts FROM caughtin4k.email_verification_tokens WHERE account_id = %s", (account_id,),
                ).fetchone()
                self.assertEqual(row["attempts"], 1)
            security.verify_email(account_id, code)
            self.assertIsNotNone(accounts.authenticate("Bearer " + token, secret)["email_verified_at"])
            with self.assertRaises(HTTPException):
                security.verify_email(account_id, code)
            with patch.object(security, "send_code") as mail:
                security.request_reset(account["email"])
                reset = mail.call_args.args[1]
            next_password = secrets.token_urlsafe(24)
            security.reset_password(account["email"], reset, next_password)
            with self.assertRaises(HTTPException):
                accounts.authenticate("Bearer " + token, secret)
            with self.assertRaises(HTTPException):
                accounts.login(account["email"], password)
            changed = accounts.login(account["email"], next_password)
            self.assertEqual(changed["id"], account_id)
            with self.assertRaises(HTTPException):
                security.reset_password(account["email"], reset, password)
            for _ in range(3):
                security.limit(limit_key, secret, 3, 900)
            with self.assertRaises(HTTPException) as caught:
                security.limit(limit_key, secret, 3, 900)
            self.assertEqual(caught.exception.status_code, 429)
            with connect() as connection:
                attempts = connection.execute(
                    "SELECT attempts FROM caughtin4k.request_limits WHERE key_hash = %s", (key_hash,),
                ).fetchone()["attempts"]
                self.assertEqual(attempts, 4)
        finally:
            with connect() as connection:
                connection.execute("DELETE FROM caughtin4k.request_limits WHERE key_hash = %s", (key_hash,))
                if account_id is not None:
                    connection.execute("DELETE FROM caughtin4k.accounts WHERE id = %s", (account_id,))

    def test_two_households_pairing_replay_revocation_and_concurrent_claim(self):
        check_schema()
        account_ids = []
        gateway_ids = []
        test_accounts = []
        password = secrets.token_urlsafe(24)
        suffix = uuid4().hex
        try:
            for label in ("a", "b"):
                account = accounts.create_account(
                    "Integration test", f"test-{label}-{suffix}@example.invalid", password,
                )
                account_ids.append(account["id"])
                test_accounts.append(account)
                self.assertEqual(accounts.memberships(account["id"]), [])
                self.assertEqual(accounts.login(account["email"], password)["id"], account["id"])
            expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            registrations = []
            for _ in range(3):
                registration = gateways.provision_gateway("Integration test gateway", expiry)
                gateway_ids.append(UUID(registration["gateway_id"]))
                registrations.append(registration)
            first, second, contested = registrations
            a = gateways.pair_gateway(account_ids[0], gateway_ids[0], first["pairing_code"], "Test A")
            b = gateways.pair_gateway(account_ids[1], gateway_ids[1], second["pairing_code"], "Test B")
            home_a, home_b = UUID(a["household_id"]), UUID(b["household_id"])
            self.assertNotEqual(home_a, home_b)
            snapshot = monitoring.MonitoringSnapshot(
                observed_at=datetime.now(timezone.utc), devices=[monitoring.DeviceMetadata(
                    mac="aa:bb:cc:dd:ee:ff", name="Integration test device",
                    status="SAFE", attack_probability=0, blocked=False,
                )], alerts=[],
                model=monitoring.ModelMetadata(available=False),
            )
            with self.assertRaises(HTTPException) as caught:
                monitoring.upload_snapshot(gateway_ids[0], second["gateway_credential"], snapshot)
            self.assertEqual(caught.exception.status_code, 401)
            uploaded = monitoring.upload_snapshot(gateway_ids[0], first["gateway_credential"], snapshot)
            self.assertTrue(uploaded["snapshot_updated"])
            replayed = monitoring.upload_snapshot(gateway_ids[0], first["gateway_credential"], snapshot)
            self.assertFalse(replayed["snapshot_updated"])
            saved = monitoring.read_snapshot(account_ids[0], home_a, gateway_ids[0])
            self.assertTrue(saved["snapshot_available"])
            self.assertEqual(len(saved["devices"]), 1)
            with self.assertRaises(HTTPException) as caught:
                monitoring.read_snapshot(account_ids[1], home_a, gateway_ids[0])
            self.assertEqual(caught.exception.status_code, 404)
            self.assertEqual(len(gateways.list_gateways(account_ids[0], home_a)), 1)
            with self.assertRaises(HTTPException) as caught:
                gateways.list_gateways(account_ids[1], home_a)
            self.assertEqual(caught.exception.status_code, 404)
            with self.assertRaises(HTTPException):
                gateways.pair_gateway(account_ids[1], gateway_ids[0], first["pairing_code"], "Replay")

            def claim(account_id):
                try:
                    return gateways.pair_gateway(
                        account_id, gateway_ids[2], contested["pairing_code"], "Contested",
                    )
                except HTTPException as error:
                    self.assertEqual(error.status_code, 400)
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(claim, account_ids))
            self.assertEqual(sum(result is not None for result in claims), 1)
            invitation = households.create_invite(
                account_ids[0], home_a, test_accounts[1]["email"], "member",
            )
            with self.assertRaises(HTTPException):
                households.accept_invite(account_ids[0], invitation["invite_code"])
            joined = households.accept_invite(account_ids[1], invitation["invite_code"])
            self.assertEqual(joined["household_role"], "member")
            self.assertEqual(len(gateways.list_gateways(account_ids[1], home_a)), 1)
            with self.assertRaises(HTTPException):
                households.accept_invite(account_ids[1], invitation["invite_code"])
            with self.assertRaises(HTTPException) as caught:
                households.create_invite(account_ids[1], home_a, "blocked@example.invalid", "member")
            self.assertEqual(caught.exception.status_code, 403)
            payload = commands.CommandInput(command_id=uuid4(), action="block", mac="aa:bb:cc:dd:ee:ff")
            for account_id, home, status in (
                (account_ids[1], home_a, 403), (account_ids[0], home_b, 404),
            ):
                with self.assertRaises(HTTPException) as caught:
                    commands.create_command(account_id, home, gateway_ids[0], payload)
                self.assertEqual(caught.exception.status_code, status)
            queued = commands.create_command(account_ids[0], home_a, gateway_ids[0], payload)
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(commands.create_command(
                account_ids[0], home_a, gateway_ids[0], payload,
            )["id"], payload.command_id)
            with self.assertRaises(HTTPException) as caught:
                commands.take_command(gateway_ids[0], second["gateway_credential"])
            self.assertEqual(caught.exception.status_code, 401)

            def take(_):
                return commands.take_command(gateway_ids[0], first["gateway_credential"])["command"]

            with ThreadPoolExecutor(max_workers=2) as pool:
                deliveries = list(pool.map(take, range(2)))
            self.assertEqual(sum(item is not None for item in deliveries), 1)
            self.assertEqual(commands.complete_command(
                gateway_ids[0], first["gateway_credential"], payload.command_id,
                commands.CommandResult(success=True, result_code="applied"),
            )["status"], "succeeded")
            self.assertEqual(commands.read_command(
                account_ids[0], home_a, gateway_ids[0], payload.command_id,
            )["status"], "succeeded")
            expiring = commands.CommandInput(command_id=uuid4(), action="unblock", mac=payload.mac)
            commands.create_command(account_ids[0], home_a, gateway_ids[0], expiring)
            with connect() as connection:
                connection.execute(
                    "UPDATE caughtin4k.gateway_commands SET expires_at = now() - interval '1 second' "
                    "WHERE id = %s", (expiring.command_id,),
                )
            self.assertIsNone(commands.take_command(gateway_ids[0], first["gateway_credential"])["command"])
            self.assertEqual(commands.read_command(
                account_ids[0], home_a, gateway_ids[0], expiring.command_id,
            )["status"], "expired")
            token_secret = secrets.token_urlsafe(32)
            token = accounts.issue_token(account, token_secret)
            self.assertEqual(accounts.authenticate("Bearer " + token, token_secret)["id"], account["id"])
            accounts.revoke_sessions(account["id"])
            with self.assertRaises(HTTPException):
                accounts.authenticate("Bearer " + token, token_secret)
        finally:
            # Delete only records identified by UUIDs created by this test.
            with connect() as connection:
                rows = connection.execute(
                    "SELECT household_id FROM caughtin4k.gateways WHERE id = ANY(%s)",
                    (gateway_ids,),
                ).fetchall()
                household_ids = [row["household_id"] for row in rows if row["household_id"]]
                connection.execute("DELETE FROM caughtin4k.gateways WHERE id = ANY(%s)", (gateway_ids,))
                connection.execute(
                    "DELETE FROM caughtin4k.household_invites WHERE household_id = ANY(%s)",
                    (household_ids,),
                )
                connection.execute(
                    "DELETE FROM caughtin4k.household_members WHERE household_id = ANY(%s)",
                    (household_ids,),
                )
                connection.execute("DELETE FROM caughtin4k.households WHERE id = ANY(%s)", (household_ids,))
                connection.execute("DELETE FROM caughtin4k.accounts WHERE id = ANY(%s)", (account_ids,))


if __name__ == "__main__":
    url = read_database_url()
    with patch.dict(os.environ, {
        "GHOST_CLOUD_DATABASE_URL": url, "GHOST_RUN_CLOUD_INTEGRATION": "true",
    }):
        # unittest evaluates skip decorators at import, before the private prompt.
        CloudIntegrationTests.__unittest_skip__ = False
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CloudIntegrationTests)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
