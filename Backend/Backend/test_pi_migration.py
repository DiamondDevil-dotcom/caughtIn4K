import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import migrate_pi_household as migration


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "backup.db"
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript("""
                CREATE TABLE accounts(email TEXT, name TEXT, password_hash TEXT, salt TEXT, created_at REAL);
                CREATE TABLE households(id INTEGER, owner_email TEXT);
                CREATE TABLE household_members(email TEXT, role TEXT, joined_at REAL);
            """)
            for email in ("owner@example.com", "member@example.com", "uninvited@example.com"):
                connection.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                                   (email, "Test", "a" * 64, "b" * 32, 1700000000))
            connection.execute("INSERT INTO households VALUES (1, 'owner@example.com')")
            connection.execute("INSERT INTO household_members VALUES ('owner@example.com', 'owner', 1700000000)")
            connection.execute("INSERT INTO household_members VALUES ('member@example.com', 'member', 1700000000)")
            connection.commit()
        finally:
            connection.close()

    def test_read_only_inspection_preserves_backup(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        backup = migration.read_backup(self.path)
        self.assertEqual(len(backup["accounts"]), 3)
        self.assertEqual(len(backup["members"]), 2)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)

    def test_missing_file_is_not_created(self):
        absent = Path(self.directory.name) / "missing.db"
        with self.assertRaises(migration.MigrationError):
            migration.read_backup(absent)
        self.assertFalse(absent.exists())

    def test_inconsistent_owner_rejected(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("UPDATE household_members SET role = 'admin' WHERE role = 'owner'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(migration.MigrationError):
            migration.read_backup(self.path)

    def test_import_preserves_passwords_roles_and_no_access_for_uninvited(self):
        backup = migration.read_backup(self.path)
        manager = MagicMock()
        db = manager.__enter__.return_value
        db.execute.return_value.fetchone.return_value = None
        with (
            patch.object(migration, "check_schema"),
            patch.object(migration, "create_private_directory"),
            patch.object(migration, "connect", return_value=manager),
            patch.object(migration, "write_private_file") as write,
        ):
            result = migration.import_backup(backup, "Home", "https://cloud.example",
                                             Path(self.directory.name) / "output", "private-url")
        inserts = [call for call in db.execute.call_args_list
                   if "INSERT INTO caughtin4k.accounts" in call.args[0]]
        self.assertEqual(len(inserts), 3)
        self.assertEqual(inserts[0].args[1][3:5], ("a" * 64, "b" * 32))
        self.assertIn("100000", inserts[0].args[0])
        membership = [call for call in db.execute.call_args_list
                      if "INSERT INTO caughtin4k.household_members" in call.args[0]]
        self.assertEqual([call.args[1][2] for call in membership], ["owner", "member"])
        self.assertEqual(result["members"], 2)
        self.assertIn("GHOST_CLOUD_UPLOAD_ENABLED=false", write.call_args_list[0].args[1])
        self.assertNotIn("pairing", write.call_args_list[0].args[1])

    def test_cloud_conflicts_stop_before_any_insert_or_bundle_write(self):
        manager = MagicMock()
        db = manager.__enter__.return_value
        db.execute.return_value.fetchone.return_value = {"exists": 1}
        with (
            patch.object(migration, "check_schema"),
            patch.object(migration, "create_private_directory"),
            patch.object(migration, "connect", return_value=manager),
            patch.object(migration, "write_private_file") as write,
        ):
            with self.assertRaises(migration.MigrationError):
                migration.import_backup(migration.read_backup(self.path), "Home", "https://cloud.example",
                                        Path(self.directory.name) / "output", "private-url")
        self.assertFalse(any("INSERT" in call.args[0] for call in db.execute.call_args_list))
        write.assert_not_called()
        self.assertIs(manager.__exit__.call_args.args[0], migration.MigrationError)


if __name__ == "__main__":
    unittest.main()
