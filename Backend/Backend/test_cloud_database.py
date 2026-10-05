import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import psycopg
from psycopg.conninfo import conninfo_to_dict

import cloud_database as cloud


class CloudDatabaseTests(unittest.TestCase):
    url = "postgresql://test_user:test_password@db.example:5432/postgres"

    def test_configuration_requires_private_credentials(self):
        for url in ("", "postgresql://db.example/postgres", "not a connection string"):
            with self.subTest(url=url), self.assertRaises(cloud.CloudDatabaseError):
                cloud.connection_settings(url)

    def test_tls_cannot_be_disabled(self):
        for mode in ("disable", "allow", "prefer"):
            with self.subTest(mode=mode), self.assertRaises(cloud.CloudDatabaseError):
                cloud.connection_settings(self.url + "?sslmode=" + mode)

    def test_tls_timeout_and_encoded_password(self):
        settings = conninfo_to_dict(cloud.connection_settings(
            "postgresql://test_user:p%40ss%3Aword@db.example:5432/postgres"
        ))
        self.assertEqual(settings["password"], "p@ss:word")
        self.assertEqual(settings["sslmode"], "require")
        self.assertEqual(settings["connect_timeout"], "10")

    def test_connection_error_does_not_disclose_credentials(self):
        with patch.object(psycopg, "connect", side_effect=psycopg.OperationalError(self.url)):
            with self.assertRaises(cloud.CloudDatabaseError) as caught:
                with cloud.connect(self.url):
                    self.fail("Unreachable connection must not succeed.")
        self.assertNotIn("test_password", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    @contextmanager
    def fake_connection(self, versions):
        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = versions
        self.connection = connection
        yield connection

    def test_initialization_applies_migration_and_records_version(self):
        with patch.object(cloud, "connect", side_effect=lambda url: self.fake_connection([])):
            cloud.initialize_schema(self.url)
        calls = self.connection.execute.call_args_list
        self.assertEqual(calls[0].args[0], "SELECT pg_advisory_xact_lock(734104001)")
        self.assertTrue(any("CREATE TABLE caughtin4k.accounts" in call.args[0] for call in calls))
        self.assertEqual(calls[-1].args[1], (cloud.SCHEMA_VERSION,))

    def test_initialization_is_idempotent(self):
        with patch.object(cloud, "connect", side_effect=lambda url: self.fake_connection([
            {"version": version} for version, _ in cloud.MIGRATIONS
        ])):
            cloud.initialize_schema(self.url)
        self.assertFalse(any(
            "CREATE TABLE caughtin4k.accounts" in call.args[0]
            for call in self.connection.execute.call_args_list
        ))

    def test_unknown_version_is_not_silently_accepted(self):
        with patch.object(cloud, "connect", side_effect=lambda url: self.fake_connection([{"version": 999}])):
            with self.assertRaises(cloud.CloudDatabaseError):
                cloud.initialize_schema(self.url)
            with self.assertRaises(cloud.CloudDatabaseError):
                cloud.check_schema(self.url)

    def test_existing_version_one_upgrades_without_recreating_accounts(self):
        with patch.object(cloud, "connect", side_effect=lambda url: self.fake_connection([{"version": 1}])):
            cloud.initialize_schema(self.url)
        queries = [call.args[0] for call in self.connection.execute.call_args_list]
        self.assertFalse(any("CREATE TABLE caughtin4k.accounts" in query for query in queries))
        self.assertTrue(any("CREATE TABLE caughtin4k.gateway_snapshots" in query for query in queries))
        self.assertEqual(self.connection.execute.call_args.args[1], (cloud.SCHEMA_VERSION,))
    def test_check_requires_applied_migration(self):
        with patch.object(cloud, "connect", side_effect=lambda url: self.fake_connection([])):
            with self.assertRaises(cloud.CloudDatabaseError):
                cloud.check_schema(self.url)

    def test_cli_prompts_privately_and_encodes_placeholder_password(self):
        with (
            patch.dict("os.environ", {"GHOST_CLOUD_DATABASE_URL": ""}),
            patch("sys.argv", ["cloud_database.py", "init"]),
            patch.object(cloud.getpass, "getpass", side_effect=[
                "postgresql://test_user:[YOUR-PASSWORD]@db.example:5432/postgres",
                "p@ss:word",
            ]),
            patch.object(cloud, "initialize_schema") as initialize,
            patch.object(cloud, "check_schema") as check,
            patch("builtins.print") as output,
        ):
            cloud.main()
        settings = conninfo_to_dict(cloud.connection_settings(initialize.call_args.args[0]))
        self.assertEqual(settings["password"], "p@ss:word")
        check.assert_called_once_with(initialize.call_args.args[0])
        self.assertNotIn("p@ss", output.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
