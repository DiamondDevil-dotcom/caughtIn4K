"""Opt-in PostgreSQL foundation; the existing Pi deployment is not switched."""

from __future__ import annotations

import argparse
import getpass
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATIONS = (
    (1, MIGRATION_DIR / "001_cloud_foundation.sql"),
    (2, MIGRATION_DIR / "002_gateway_monitoring.sql"),
    (3, MIGRATION_DIR / "003_gateway_commands.sql"),
    (4, MIGRATION_DIR / "004_customer_accounts.sql"),
    (5, MIGRATION_DIR / "005_device_management.sql"),
    (6, MIGRATION_DIR / "006_push_notifications.sql"),
    (7, MIGRATION_DIR / "007_federated_training.sql"),
)
SCHEMA_VERSION = MIGRATIONS[-1][0]


class CloudDatabaseError(RuntimeError):
    """Safe operational error that does not expose connection credentials."""


def connection_settings(url: str | None = None) -> str:
    value = url if url is not None else os.getenv("GHOST_CLOUD_DATABASE_URL", "")
    if not value.strip():
        raise CloudDatabaseError("Set GHOST_CLOUD_DATABASE_URL privately before using cloud storage.")
    try:
        settings = conninfo_to_dict(value)
    except psycopg.ProgrammingError:
        raise CloudDatabaseError("Cloud database connection settings are invalid.") from None
    if not all(settings.get(key) for key in ("host", "dbname", "user", "password")):
        raise CloudDatabaseError("Cloud database settings need a host, database, user, and password.")
    if settings.get("sslmode") not in (None, "require", "verify-ca", "verify-full"):
        raise CloudDatabaseError("Cloud database connections must use TLS.")
    return make_conninfo(
        value,
        sslmode=settings.get("sslmode", "require"),
        connect_timeout="10",
        application_name="caughtin4k-backend",
    )


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection]:
    settings = connection_settings(url)
    try:
        with psycopg.connect(settings, row_factory=dict_row) as connection:
            yield connection
    except psycopg.Error:
        # Driver diagnostics can include usernames/hosts; do not echo credentials.
        raise CloudDatabaseError(
            "Cloud database operation failed. Check connectivity, credentials, and schema permissions."
        ) from None


def initialize_schema(url: str | None = None) -> None:
    with connect(url) as connection:
        # Serialize bootstrap across backend instances; DDL and version commit together.
        connection.execute("SELECT pg_advisory_xact_lock(734104001)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS caughtin4k")
        connection.execute("REVOKE ALL ON SCHEMA caughtin4k FROM PUBLIC")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS caughtin4k.schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        connection.execute("ALTER TABLE caughtin4k.schema_migrations ENABLE ROW LEVEL SECURITY")
        connection.execute("REVOKE ALL ON caughtin4k.schema_migrations FROM PUBLIC")
        versions = connection.execute(
            "SELECT version FROM caughtin4k.schema_migrations ORDER BY version"
        ).fetchall()
        applied = [row["version"] for row in versions]
        expected = [version for version, _ in MIGRATIONS]
        if applied != expected[:len(applied)]:
            raise CloudDatabaseError("Cloud schema version is unsupported by this backend.")
        for version, path in MIGRATIONS[len(applied):]:
            connection.execute(path.read_text(encoding="utf-8"), prepare=False)
            connection.execute(
                "INSERT INTO caughtin4k.schema_migrations(version) VALUES (%s)", (version,)
            )


def check_schema(url: str | None = None) -> None:
    with connect(url) as connection:
        rows = connection.execute(
            "SELECT version FROM caughtin4k.schema_migrations ORDER BY version"
        ).fetchall()
        if [row["version"] for row in rows] != [version for version, _ in MIGRATIONS]:
            raise CloudDatabaseError("Cloud schema is not ready for this backend.")


def read_database_url() -> str:
    url = os.getenv("GHOST_CLOUD_DATABASE_URL", "")
    if not url:
        url = getpass.getpass("Session pooler PostgreSQL URL (hidden): ").strip()
        if "[YOUR-PASSWORD]" in url:
            password = getpass.getpass("Database password (hidden): ")
            url = url.replace("[YOUR-PASSWORD]", quote(password, safe=""))
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="Private cloud database setup; does not migrate Pi data.")
    parser.add_argument("action", choices=("init", "check"))
    args = parser.parse_args()
    try:
        url = read_database_url()
        if args.action == "init":
            initialize_schema(url)
        check_schema(url)
    except CloudDatabaseError as error:
        parser.exit(1, f"{error}\n")
    print(f"Cloud database schema version {SCHEMA_VERSION} is ready. Existing Pi routing is unchanged.")


if __name__ == "__main__":
    main()
