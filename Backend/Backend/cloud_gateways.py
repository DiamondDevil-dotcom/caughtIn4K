"""Provisioning is operator-only; account pairing consumes a one-time secret."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from cloud_database import connect


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_name(name: str) -> str:
    value = name.strip()
    if not 1 <= len(value) <= 200:
        raise HTTPException(status_code=400, detail="Use a name between 1 and 200 characters.")
    return value


def provision_gateway(name: str, expires_at: datetime) -> dict[str, Any]:
    """Call only from trusted provisioning tooling, never a public account route."""
    registration = prepare_registration(name, expires_at)
    with connect() as connection:
        insert_registration(connection, name.strip(), registration)
    return registration


def prepare_registration(name: str, expires_at: datetime) -> dict[str, Any]:
    name = validate_name(name)
    if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
        raise ValueError("Provisioning requires a future timezone-aware pairing expiry.")
    gateway_id = uuid4()
    credential = secrets.token_urlsafe(32)
    pairing_code = secrets.token_urlsafe(32)
    return {
        "gateway_id": str(gateway_id),
        "gateway_credential": credential,
        "pairing_code": pairing_code,
        "pairing_expires_at": expires_at.isoformat(),
        # Only the consumer pairing secret goes on the label, never the Pi credential.
        "qr_payload": json.dumps({
            "version": 1, "gateway_id": str(gateway_id), "pairing_code": pairing_code,
        }, separators=(",", ":")),
    }


def insert_registration(connection, name: str, registration: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO caughtin4k.gateways "
        "(id, name, credential_hash, pairing_code_hash, pairing_expires_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            UUID(registration["gateway_id"]), validate_name(name),
            secret_hash(registration["gateway_credential"]),
            secret_hash(registration["pairing_code"]),
            datetime.fromisoformat(registration["pairing_expires_at"]),
        ),
    )


def pair_gateway(
    account_id: UUID, gateway_id: UUID, pairing_code: str, household_name: str,
) -> dict[str, Any]:
    household_name = validate_name(household_name)
    code = pairing_code.strip()
    if not 1 <= len(code) <= 256:
        raise HTTPException(status_code=400, detail="Gateway setup code is invalid or unavailable.")
    digest = secret_hash(code)
    household_id = uuid4()
    with connect() as connection:
        # The row lock serializes claims. The second claimant sees the consumed code.
        gateway = connection.execute(
            "SELECT id, name FROM caughtin4k.gateways "
            "WHERE id = %s AND pairing_code_hash = %s "
            "AND pairing_expires_at > now() AND household_id IS NULL AND revoked_at IS NULL "
            "FOR UPDATE",
            (gateway_id, digest),
        ).fetchone()
        if gateway is None:
            raise HTTPException(status_code=400, detail="Gateway setup code is invalid or unavailable.")
        connection.execute(
            "INSERT INTO caughtin4k.households (id, name, owner_account_id) VALUES (%s, %s, %s)",
            (household_id, household_name, account_id),
        )
        connection.execute(
            "INSERT INTO caughtin4k.household_members (household_id, account_id, role) "
            "VALUES (%s, %s, 'owner')",
            (household_id, account_id),
        )
        connection.execute(
            "UPDATE caughtin4k.gateways SET household_id = %s, "
            "pairing_code_hash = NULL, pairing_expires_at = NULL WHERE id = %s",
            (household_id, gateway_id),
        )
    return {
        "success": True, "gateway_id": str(gateway_id),
        "household_id": str(household_id), "household_role": "owner",
    }


def list_gateways(account_id: UUID, household_id: UUID) -> list[dict[str, Any]]:
    with connect() as connection:
        membership = connection.execute(
            "SELECT role FROM caughtin4k.household_members "
            "WHERE household_id = %s AND account_id = %s",
            (household_id, account_id),
        ).fetchone()
        if membership is None:
            # Same response for nonexistent and unauthorized households.
            raise HTTPException(status_code=404, detail="Household not found.")
        return connection.execute(
            "SELECT g.id AS gateway_id, g.name, g.last_seen_at, g.revoked_at "
            "FROM caughtin4k.gateways g "
            "JOIN caughtin4k.household_members m ON m.household_id = g.household_id "
            "WHERE g.household_id = %s AND m.account_id = %s ORDER BY g.created_at, g.id",
            (household_id, account_id),
        ).fetchall()
