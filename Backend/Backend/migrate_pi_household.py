"""Explicit, read-only SQLite import into cloud accounts; no live Pi changes."""

from __future__ import annotations

import argparse
import re
import secrets
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from cloud_accounts import normalize_email
from cloud_database import CloudDatabaseError, check_schema, connect, read_database_url
from cloud_gateways import secret_hash, validate_name
from cloud_uploader_config import validate_cloud_origin
from provision_cloud_gateway import ProvisioningError, create_private_directory, write_private_file


class MigrationError(RuntimeError):
    pass


def read_backup(path: Path) -> dict:
    if not path.is_file():
        raise MigrationError("SQLite backup was not found.")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("SQLite backup integrity check failed.")
        accounts = [dict(row) for row in connection.execute(
            "SELECT email, name, password_hash, salt, created_at FROM accounts"
        )]
        homes = connection.execute("SELECT id, owner_email FROM households").fetchall()
        members = [dict(row) for row in connection.execute(
            "SELECT email, role, joined_at FROM household_members"
        )]
    finally:
        connection.close()
    if len(homes) != 1 or homes[0]["id"] != 1:
        raise MigrationError("Expected exactly one claimed Pi household.")
    emails = set()
    for account in accounts:
        email = normalize_email(account["email"])
        if email in emails:
            raise MigrationError("Backup contains duplicate normalized account emails.")
        emails.add(email)
        account["email"] = email
        if not 1 <= len(account["name"].strip()) <= 200:
            raise MigrationError("Backup contains an invalid account name.")
        if not re.fullmatch(r"[0-9a-f]{64}", account["password_hash"]):
            raise MigrationError("Backup contains an unsupported password hash.")
        if not re.fullmatch(r"[0-9a-f]{32}", account["salt"]):
            raise MigrationError("Backup contains an unsupported password salt.")
        account["created_at"] = datetime.fromtimestamp(account["created_at"], timezone.utc)
    owner = normalize_email(homes[0]["owner_email"])
    member_emails = set()
    owners = []
    for member in members:
        member["email"] = normalize_email(member["email"])
        if member["email"] not in emails or member["email"] in member_emails:
            raise MigrationError("Backup membership does not match a unique account.")
        member_emails.add(member["email"])
        if member["role"] not in {"owner", "admin", "member"}:
            raise MigrationError("Backup contains an unsupported household role.")
        if member["role"] == "owner":
            owners.append(member["email"])
        member["joined_at"] = datetime.fromtimestamp(member["joined_at"], timezone.utc)
    if owners != [owner]:
        raise MigrationError("Backup household ownership is inconsistent.")
    return {"accounts": accounts, "members": members, "owner_email": owner}


def import_backup(backup: dict, name: str, cloud_url: str, output: Path, database_url: str) -> dict:
    name = validate_name(name)
    cloud_url = validate_cloud_origin(cloud_url)
    check_schema(database_url)
    create_private_directory(output)
    household_id, gateway_id = uuid4(), uuid4()
    credential = secrets.token_urlsafe(32)
    ids = {account["email"]: uuid4() for account in backup["accounts"]}
    with connect(database_url) as connection:
        # Serialize this operator import. Unique email constraints also prevent races with signup.
        connection.execute("SELECT pg_advisory_xact_lock(734104002)")
        existing = connection.execute(
            "SELECT 1 FROM caughtin4k.accounts WHERE email = ANY(%s) LIMIT 1",
            (list(ids),),
        ).fetchone()
        if existing:
            raise MigrationError("Cloud account conflict: import refused; no accounts were overwritten.")
        for account in backup["accounts"]:
            connection.execute(
                "INSERT INTO caughtin4k.accounts "
                "(id, email, name, password_hash, password_salt, password_algorithm, "
                "password_iterations, created_at) VALUES (%s, %s, %s, %s, %s, "
                "'pbkdf2_sha256', 100000, %s)",
                (
                    ids[account["email"]], account["email"], account["name"],
                    account["password_hash"], account["salt"], account["created_at"],
                ),
            )
        connection.execute(
            "INSERT INTO caughtin4k.households (id, name, owner_account_id) VALUES (%s, %s, %s)",
            (household_id, name, ids[backup["owner_email"]]),
        )
        for member in backup["members"]:
            connection.execute(
                "INSERT INTO caughtin4k.household_members "
                "(household_id, account_id, role, joined_at) VALUES (%s, %s, %s, %s)",
                (household_id, ids[member["email"]], member["role"], member["joined_at"]),
            )
        connection.execute(
            "INSERT INTO caughtin4k.gateways (id, household_id, name, credential_hash) "
            "VALUES (%s, %s, %s, %s)",
            (gateway_id, household_id, name, secret_hash(credential)),
        )
        # The imported gateway is already owned; there is deliberately no pairing code.
        write_private_file(output / "gateway.env", (
            "GHOST_CLOUD_UPLOAD_ENABLED=false\n"
            f"GHOST_CLOUD_API_URL={cloud_url}\n"
            f"GHOST_CLOUD_GATEWAY_ID={gateway_id}\n"
            f"GHOST_CLOUD_GATEWAY_CREDENTIAL={credential}\n"
        ))
        write_private_file(output / "migration-ids.txt", (
            f"household_id={household_id}\ngateway_id={gateway_id}\n"
        ))
    return {
        "accounts": len(ids), "members": len(backup["members"]),
        "household_id": str(household_id), "gateway_id": str(gateway_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a Pi backup; importing requires --apply.")
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--name")
    parser.add_argument("--cloud-url")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        backup = read_backup(args.backup)
        print(f"Backup validated: {len(backup['accounts'])} accounts, {len(backup['members'])} household members.")
        if not args.apply:
            print("Inspection only. No cloud writes or Pi changes.")
            return
        if not args.name or not args.cloud_url or args.output is None:
            raise MigrationError("Import requires --name, --cloud-url, and a new private --output folder.")
        result = import_backup(backup, args.name, args.cloud_url, args.output, read_database_url())
    except (MigrationError, CloudDatabaseError, ProvisioningError) as error:
        parser.exit(1, f"{error}\nDo not use partial output; reconcile any uncertain commit before retrying.\n")
    except (OSError, ValueError, TypeError, sqlite3.Error, subprocess.SubprocessError, HTTPException):
        parser.exit(1, "Backup inspection/import failed. Check input format, paths, and permissions; "
                    "no successful import confirmed. Do not use partial output.\n")
    print(f"Imported {result['accounts']} accounts and {result['members']} memberships.")
    print("Private gateway bundle saved with upload disabled. Live Pi login and FL are unchanged.")


if __name__ == "__main__":
    main()
