"""Operator-only provisioning; secrets go to a protected folder, not stdout."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from cloud_database import CloudDatabaseError, check_schema, connect, read_database_url
from cloud_gateways import insert_registration, prepare_registration
from cloud_uploader_config import validate_cloud_origin
from cloud_accounts import normalize_email


class ProvisioningError(RuntimeError):
    pass


def create_private_directory(path: Path) -> None:
    if not path.is_absolute():
        raise ProvisioningError("Use an absolute output path outside the source repository.")
    repository = Path(__file__).resolve().parents[2]
    if path.resolve().is_relative_to(repository):
        raise ProvisioningError("Provisioning credentials must be stored outside the source repository.")
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == "nt":
        identity = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if not identity.startswith("S-1-") or not all(c.isdigit() or c in "S-" for c in identity):
            raise ProvisioningError("Could not determine the current Windows account SID.")
        subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{identity}:(OI)(CI)F"],
            check=True, capture_output=True, text=True,
        )
    else:
        path.chmod(0o700)


def write_private_file(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def provision_bundle(name: str, expiry: datetime, cloud_url: str, output: Path, *, consumer_setup: bool = False,
                     verified_order: str | None = None, purchaser_email: str | None = None) -> str:
    cloud_url = validate_cloud_origin(cloud_url)
    if (verified_order is None) != (purchaser_email is None):
        raise ValueError("Supply both the verified order and purchaser email.")
    if verified_order is not None:
        verified_order = verified_order.strip()
        if not 1 <= len(verified_order) <= 200:
            raise ValueError("Invalid verified order reference.")
        purchaser_email = normalize_email(purchaser_email)
    registration = prepare_registration(name, expiry)
    create_private_directory(output)
    # Secret files are durable before commit; a write failure rolls back registration.
    with connect() as connection:
        insert_registration(connection, name, registration)
        if verified_order is not None:
            connection.execute(
                "INSERT INTO caughtin4k.gateway_purchases "
                "(gateway_id, order_reference, purchaser_email) VALUES (%s, %s, %s)",
                (registration["gateway_id"], verified_order, purchaser_email),
            )
        if consumer_setup:
            connection.execute(
                "UPDATE caughtin4k.gateways SET consumer_setup = TRUE WHERE id = %s",
                (registration["gateway_id"],),
            )
        write_private_file(output / "gateway.env", (
            "GHOST_CLOUD_UPLOAD_ENABLED=false\n"
            f"GHOST_CLOUD_API_URL={cloud_url}\n"
            f"GHOST_CLOUD_GATEWAY_ID={registration['gateway_id']}\n"
            f"GHOST_CLOUD_GATEWAY_CREDENTIAL={registration['gateway_credential']}\n"
        ))
        write_private_file(output / "pairing-label.json", registration["qr_payload"] + "\n")
        write_private_file(output / "pairing-expiry.txt", registration["pairing_expires_at"] + "\n")
        if consumer_setup:
            write_private_file(output / "consumer-setup.txt", "enabled\n")
    return registration["gateway_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a NEW Pi; does not migrate an existing household.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--expires-at", required=True, help="ISO timestamp with timezone; set for the intended setup window.")
    parser.add_argument("--cloud-url", required=True, help="HTTPS origin of the backend.")
    parser.add_argument("--output", required=True, type=Path, help="New private folder outside the repository.")
    parser.add_argument("--consumer-setup", action="store_true", help="Enable the factory image's Sentra Wi-Fi wizard for this NEW gateway.")
    parser.add_argument("--verified-order", help="Manufacturer-verified unique order reference for this unit.")
    parser.add_argument("--purchaser-email", help="Purchaser email from the verified order, never customer self-attestation.")
    args = parser.parse_args()
    try:
        expiry = datetime.fromisoformat(args.expires_at)
        url = read_database_url()
        previous_url = os.environ.get("GHOST_CLOUD_DATABASE_URL")
        os.environ["GHOST_CLOUD_DATABASE_URL"] = url
        try:
            check_schema()
            gateway_id = provision_bundle(
                args.name, expiry, args.cloud_url, args.output, consumer_setup=args.consumer_setup,
                verified_order=args.verified_order, purchaser_email=args.purchaser_email,
            )
        finally:
            if previous_url is None:
                del os.environ["GHOST_CLOUD_DATABASE_URL"]
            else:
                os.environ["GHOST_CLOUD_DATABASE_URL"] = previous_url
    except (ValueError, HTTPException):
        parser.exit(1, "Invalid name, cloud origin, or expiry. No successful provisioning confirmed.\n")
    except (OSError, subprocess.SubprocessError, ProvisioningError, CloudDatabaseError):
        parser.exit(
            1, "Provisioning failed. Do not use any partial output bundle. "
            "A database commit failure may need operator reconciliation; do not retry into the same folder.\n",
        )
    print(f"Gateway {gateway_id} registered; private bundle saved. Uploader remains disabled.")
    print("Keep gateway.env on the Pi only; pairing-label.json is for the customer's private setup label.")


if __name__ == "__main__":
    main()
