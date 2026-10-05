"""Bounded outbound controls; delivery is not proof of firewall enforcement."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cloud_database import connect
from cloud_gateways import secret_hash


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    action: Literal["block", "unblock"]
    mac: str = Field(pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool = Field(strict=True)
    result_code: Literal["applied", "enforcement_failed", "local_rejected", "local_unreachable", "expired"]

    @model_validator(mode="after")
    def truthful_result(self):
        if self.success != (self.result_code == "applied"):
            raise ValueError("Only confirmed enforcement may be marked successful.")
        return self


def _expire(connection, gateway_id: UUID) -> None:
    connection.execute(
        "UPDATE caughtin4k.gateway_commands SET status = CASE "
        "WHEN status = 'queued' THEN 'expired' ELSE 'unknown' END "
        "WHERE gateway_id = %s AND status IN ('queued', 'delivered') AND expires_at <= clock_timestamp()",
        (gateway_id,),
    )


def _user_gateway(connection, account_id: UUID, home: UUID, gateway_id: UUID, *, manage: bool):
    row = connection.execute(
        "SELECT g.id, m.role FROM caughtin4k.gateways g "
        "JOIN caughtin4k.household_members m ON m.household_id = g.household_id "
        "WHERE g.id = %s AND g.household_id = %s AND m.account_id = %s "
        "AND g.revoked_at IS NULL FOR UPDATE OF g FOR SHARE OF m",
        (gateway_id, home, account_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Gateway not found.")
    if manage and row["role"] not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only household owners and admins can control the network.")
    return row


def _machine_gateway(connection, gateway_id: UUID, credential: str):
    if not 32 <= len(credential) <= 256:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    row = connection.execute(
        "SELECT id, household_id FROM caughtin4k.gateways WHERE id = %s "
        "AND credential_hash = %s AND revoked_at IS NULL FOR UPDATE",
        (gateway_id, secret_hash(credential)),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    if row["household_id"] is None:
        raise HTTPException(status_code=409, detail="Pair this gateway before accepting commands.")
    return row


def create_command(account_id: UUID, home: UUID, gateway_id: UUID, payload: CommandInput) -> dict:
    with connect() as connection:
        _user_gateway(connection, account_id, home, gateway_id, manage=True)
        _expire(connection, gateway_id)
        existing = connection.execute(
            "SELECT * FROM caughtin4k.gateway_commands WHERE id = %s", (payload.command_id,),
        ).fetchone()
        if existing is not None:
            if (
                existing["gateway_id"] != gateway_id or existing["created_by"] != account_id
                or existing["action"] != payload.action or existing["mac"] != payload.mac
            ):
                raise HTTPException(status_code=409, detail="Command ID is already in use.")
            return existing
        active = connection.execute(
            "SELECT id FROM caughtin4k.gateway_commands "
            "WHERE gateway_id = %s AND status IN ('queued', 'delivered')",
            (gateway_id,),
        ).fetchone()
        if active is not None:
            raise HTTPException(status_code=409, detail="Wait for the current gateway command to finish.")
        device = connection.execute(
            "SELECT 1 FROM caughtin4k.gateway_snapshots "
            "WHERE gateway_id = %s AND devices @> %s::jsonb",
            (gateway_id, '[{"mac":"' + payload.mac + '"}]'),
        ).fetchone()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found in this gateway snapshot.")
        inserted = connection.execute(
            "INSERT INTO caughtin4k.gateway_commands (id, gateway_id, created_by, action, mac) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING *",
            (payload.command_id, gateway_id, account_id, payload.action, payload.mac),
        ).fetchone()
        if inserted is None:
            raise HTTPException(status_code=409, detail="Command ID is already in use.")
        return inserted


def read_command(account_id: UUID, home: UUID, gateway_id: UUID, command_id: UUID) -> dict:
    with connect() as connection:
        _user_gateway(connection, account_id, home, gateway_id, manage=False)
        _expire(connection, gateway_id)
        row = connection.execute(
            "SELECT * FROM caughtin4k.gateway_commands WHERE id = %s AND gateway_id = %s",
            (command_id, gateway_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Command not found.")
        return row


def take_command(gateway_id: UUID, credential: str) -> dict:
    if not 32 <= len(credential) <= 256:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    with connect() as connection:
        gateway = _machine_gateway(connection, gateway_id, credential)
        _expire(connection, gateway_id)
        row = connection.execute(
            "SELECT * FROM caughtin4k.gateway_commands "
            "WHERE gateway_id = %s AND status = 'queued' FOR UPDATE",
            (gateway_id,),
        ).fetchone()
        if row is None:
            return {"command": None}
        membership = connection.execute(
            "SELECT role FROM caughtin4k.household_members "
            "WHERE household_id = %s AND account_id = %s FOR SHARE",
            (gateway["household_id"], row["created_by"]),
        ).fetchone()
        if membership is None or membership["role"] not in {"owner", "admin"}:
            connection.execute(
                "UPDATE caughtin4k.gateway_commands SET status = 'cancelled' WHERE id = %s",
                (row["id"],),
            )
            return {"command": None}
        delivered = connection.execute(
            "UPDATE caughtin4k.gateway_commands SET status = 'delivered', delivered_at = clock_timestamp() "
            "WHERE id = %s AND expires_at > clock_timestamp() RETURNING id",
            (row["id"],),
        ).fetchone()
        if delivered is None:
            connection.execute(
                "UPDATE caughtin4k.gateway_commands SET status = 'expired' WHERE id = %s",
                (row["id"],),
            )
            return {"command": None}
        # Never redeliver: a lost response/acknowledgement must not replay a firewall action.
        return {"command": {
            "command_id": str(row["id"]), "action": row["action"], "mac": row["mac"],
            "expires_at": row["expires_at"],
        }}


def complete_command(gateway_id: UUID, credential: str, command_id: UUID, result: CommandResult) -> dict:
    if not 32 <= len(credential) <= 256:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    status = "succeeded" if result.success else "unknown" if result.result_code == "local_unreachable" else "failed"
    with connect() as connection:
        _machine_gateway(connection, gateway_id, credential)
        row = connection.execute(
            "SELECT status, result_code FROM caughtin4k.gateway_commands "
            "WHERE id = %s AND gateway_id = %s FOR UPDATE",
            (command_id, gateway_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Command not found.")
        if row["status"] in {"succeeded", "failed"} or (
            row["status"] == "unknown" and row["result_code"] is not None
        ):
            if row["status"] != status or row["result_code"] != result.result_code:
                raise HTTPException(status_code=409, detail="Command result is already recorded.")
        elif row["status"] not in {"delivered", "unknown"}:
            raise HTTPException(status_code=409, detail="Command was not delivered.")
        else:
            connection.execute(
                "UPDATE caughtin4k.gateway_commands SET status = %s, result_code = %s, "
                "completed_at = now() WHERE id = %s",
                (status, result.result_code, command_id),
            )
    return {"success": True, "status": status}
