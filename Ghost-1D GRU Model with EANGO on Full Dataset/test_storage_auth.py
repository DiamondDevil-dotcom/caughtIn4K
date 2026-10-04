import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import storage


class HouseholdStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "router_ids.db"
        self.db_patch = patch.object(storage, "DB_PATH", str(self.db_path))
        self.db_patch.start()
        self.pairing_patch = patch.dict(os.environ, {"GHOST_GATEWAY_PAIRING_CODE": "one-time-test-setup-code"})
        self.pairing_patch.start()
        storage.init_db()

    def tearDown(self):
        self.pairing_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _device(self, mac):
        return SimpleNamespace(
            mac=mac,
            name="Test IoT device",
            ip_address="192.168.4.20",
            last_seen=1_700_000_000.0,
            status="SAFE",
            attack_probability=0.01,
            blocked=False,
        )

    def test_unclaimed_devices_are_hidden_then_assigned_on_owner_claim(self):
        storage.upsert_device(self._device("aa:bb:cc:dd:ee:ff"))
        self.assertFalse(storage.is_household_device("aa:bb:cc:dd:ee:ff"))
        self.assertEqual(storage.all_devices(), [])

        with storage._connect() as connection:
            salt = os.urandom(16)
            connection.execute(
                "INSERT INTO accounts (email, name, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    "owner@example.com",
                    "Owner",
                    storage._hash_password("correct-password", salt),
                    salt.hex(),
                    1_700_000_000.0,
                ),
            )

        claimed, error, role = storage.claim_gateway(
            "owner@example.com", "one-time-test-setup-code"
        )
        self.assertTrue(claimed, error)
        self.assertEqual(role, "owner")
        self.assertTrue(storage.is_household_device("aa:bb:cc:dd:ee:ff"))
        self.assertEqual(storage.household_role("owner@example.com"), "owner")

        claimed_again, error, _ = storage.claim_gateway(
            "owner@example.com", "one-time-test-setup-code"
        )
        self.assertFalse(claimed_again)
        self.assertIn("already been claimed", error)

    def test_account_creation_requires_pairing_or_matching_invite(self):
        self.assertEqual(
            storage.create_account("Owner", "owner@example.com", "correct-password", "wrong-code")[0],
            False,
        )
        created, error = storage.create_account(
            "Owner", "owner@example.com", "correct-password", "one-time-test-setup-code"
        )
        self.assertTrue(created, error)
        self.assertEqual(storage.household_role("owner@example.com"), "owner")

        ok, error, invite = storage.create_invite(
            "owner@example.com", "member@example.com", "member"
        )
        self.assertTrue(ok, error)
        rejected, error = storage.create_account(
            "Member", "someone-else@example.com", "correct-password", invite["invite_code"]
        )
        self.assertFalse(rejected)
        self.assertIn("invitation", error)

        accepted, error = storage.create_account(
            "Member", "member@example.com", "correct-password", invite["invite_code"]
        )
        self.assertTrue(accepted, error)
        self.assertEqual(storage.household_role("member@example.com"), "member")
        replayed, error = storage.create_account(
            "Second", "second@example.com", "correct-password", invite["invite_code"]
        )
        self.assertFalse(replayed)
        self.assertIn("invitation", error)

    def test_existing_account_can_join_only_with_its_email_bound_invite(self):
        storage.create_account(
            "Owner", "owner@example.com", "correct-password", "one-time-test-setup-code"
        )
        with storage._connect() as connection:
            salt = os.urandom(16)
            connection.execute(
                "INSERT INTO accounts (email, name, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    "existing@example.com",
                    "Existing user",
                    storage._hash_password("correct-password", salt),
                    salt.hex(),
                    1_700_000_000.0,
                ),
            )
        ok, error, invite = storage.create_invite(
            "owner@example.com", "existing@example.com", "member"
        )
        self.assertTrue(ok, error)
        accepted, error, _ = storage.accept_invite(
            "someone-else@example.com", invite["invite_code"]
        )
        self.assertFalse(accepted)
        self.assertEqual(storage.household_role("existing@example.com"), None)
        accepted, error, role = storage.accept_invite(
            "existing@example.com", invite["invite_code"]
        )
        self.assertTrue(accepted, error)
        self.assertEqual(role, "member")

    def test_password_reset_codes_are_limited_to_five_attempts(self):
        storage.create_account(
            "Owner", "owner@example.com", "correct-password", "one-time-test-setup-code"
        )
        self.assertTrue(storage.create_password_reset("owner@example.com", "123456", 1_900_000_000))
        for _ in range(5):
            success, _ = storage.reset_password("owner@example.com", "wrong", "new-password")
            self.assertFalse(success)
        success, error = storage.reset_password("owner@example.com", "123456", "new-password")
        self.assertFalse(success)
        self.assertIn("invalid or expired", error)


if __name__ == "__main__":
    unittest.main()
