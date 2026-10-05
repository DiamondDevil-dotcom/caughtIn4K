"""Read-only verification of a migrated owner using privately entered credentials."""

import argparse
import getpass
import os
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

import cloud_accounts as accounts
import cloud_gateways as gateways
from cloud_database import CloudDatabaseError, check_schema, read_database_url


def read_ids(bundle: Path) -> tuple[UUID, UUID]:
    lines = (bundle / "migration-ids.txt").read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines)
    if len(lines) != 2 or set(values) != {"household_id", "gateway_id"}:
        raise ValueError("Invalid migration identifiers.")
    return UUID(values["household_id"]), UUID(values["gateway_id"])


def verify_owner(email: str, password: str, household_id: UUID, gateway_id: UUID) -> None:
    account = accounts.login(email, password)
    memberships = accounts.memberships(account["id"])
    if not any(
        UUID(str(member["household_id"])) == household_id and member["role"] == "owner"
        for member in memberships
    ):
        raise ValueError("This account is not the imported household owner.")
    registered = gateways.list_gateways(account["id"], household_id)
    if not any(
        UUID(str(gateway["gateway_id"])) == gateway_id and gateway["revoked_at"] is None
        for gateway in registered
    ):
        raise ValueError("The imported gateway is missing or revoked.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify imported owner login without changing any data.")
    parser.add_argument("--bundle", required=True, type=Path)
    args = parser.parse_args()
    previous_url = os.environ.get("GHOST_CLOUD_DATABASE_URL")
    try:
        household_id, gateway_id = read_ids(args.bundle)
        os.environ["GHOST_CLOUD_DATABASE_URL"] = read_database_url()
        check_schema()
        email = getpass.getpass("Existing owner account email (hidden): ")
        password = getpass.getpass("Existing caughtIn4K account password (hidden): ")
        verify_owner(email, password, household_id, gateway_id)
    except HTTPException as error:
        parser.exit(1, f"Verification failed: {error.detail}\n")
    except CloudDatabaseError as error:
        parser.exit(1, f"{error}\n")
    except (OSError, ValueError, KeyError):
        parser.exit(1, "Verification failed: check the migration bundle and imported ownership.\n")
    finally:
        if previous_url is None:
            os.environ.pop("GHOST_CLOUD_DATABASE_URL", None)
        else:
            os.environ["GHOST_CLOUD_DATABASE_URL"] = previous_url
    print("VERIFIED: existing owner password, cloud owner membership, and imported gateway.")
    print("Read-only check complete. Live Pi login and federated learning are unchanged.")


if __name__ == "__main__":
    main()
