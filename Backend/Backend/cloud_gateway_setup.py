"""Opt-in consumer setup, separate from device commands and monitoring."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator

from cloud_commands import _user_gateway
from cloud_database import connect
from cloud_gateways import secret_hash

CHECKS = {"ethernet", "wifi", "router", "model", "firewall"}
ERRORS = {"network_configuration_failed", "local_checks_failed"}


class WifiInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    ssid: str
    password: SecretStr

    @field_validator("ssid")
    @classmethod
    def valid_ssid(cls, value: str) -> str:
        if not 1 <= len(value.encode("utf-8")) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a Wi-Fi name of 1–32 bytes without control characters.")
        return value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not 8 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password):
            raise ValueError("Use a Wi-Fi password of 8–63 printable ASCII characters.")
        return value


class SetupReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    checks: dict[str, bool]
    error_code: str | None = None

    @field_validator("checks", mode="before")
    @classmethod
    def valid_checks(cls, value):
        if not isinstance(value, dict) or set(value) != CHECKS or any(type(v) is not bool for v in value.values()):
            raise ValueError("Supply all setup checks as booleans.")
        return value

    @field_validator("error_code")
    @classmethod
    def valid_error(cls, value):
        if value is not None and value not in ERRORS:
            raise ValueError("Unknown setup error code.")
        return value


def setup_cipher() -> Fernet:
    if os.getenv("GHOST_CLOUD_SETUP_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=503, detail="Consumer setup is not enabled on this service.")
    try:
        return Fernet(os.environ["GHOST_CLOUD_SETUP_KEY"].encode("ascii"))
    except (KeyError, ValueError, UnicodeError):
        raise HTTPException(status_code=503, detail="Consumer setup encryption is unavailable.") from None


def _machine(connection, gateway_id: UUID, credential: str):
    if not 32 <= len(credential) <= 256:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    row = connection.execute(
        "SELECT household_id, consumer_setup FROM caughtin4k.gateways WHERE id = %s AND credential_hash = %s "
        "AND revoked_at IS NULL FOR UPDATE", (gateway_id, secret_hash(credential)),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    if not row["consumer_setup"]:
        raise HTTPException(status_code=409, detail="This gateway does not support consumer setup.")
    return row


def _user(connection, account_id, home, gateway_id, *, manage):
    _user_gateway(connection, account_id, home, gateway_id, manage=manage)
    row = connection.execute(
        "SELECT consumer_setup FROM caughtin4k.gateways WHERE id = %s", (gateway_id,),
    ).fetchone()
    if not row["consumer_setup"]:
        raise HTTPException(status_code=409, detail="This gateway does not support consumer setup.")


def configure_wifi(account_id: UUID, home: UUID, gateway_id: UUID, body: dict) -> dict:
    cipher = setup_cipher()
    try:
        payload = WifiInput.model_validate(body)
    except ValidationError:
        # Never echo a Wi-Fi password via FastAPI's default validation response.
        raise HTTPException(
            status_code=400, detail="Use a valid request ID, a Wi-Fi name of 1–32 bytes, "
            "and a password of 8–63 printable ASCII characters.",
        ) from None
    plain = json.dumps({"ssid": payload.ssid, "password": payload.password.get_secret_value()}, separators=(",", ":"))
    fingerprint = hmac.new(
        os.environ["GHOST_CLOUD_SETUP_KEY"].encode("ascii"), plain.encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    with connect() as connection:
        _user(connection, account_id, home, gateway_id, manage=True)
        existing = connection.execute(
            "SELECT * FROM caughtin4k.gateway_setup WHERE gateway_id = %s", (gateway_id,),
        ).fetchone()
        if existing and existing["request_id"] == payload.request_id:
            if not hmac.compare_digest(existing["fingerprint"], fingerprint):
                raise HTTPException(status_code=409, detail="Setup request ID is already in use.")
            return {"request_id": str(payload.request_id)}
        inserted = connection.execute(
            "INSERT INTO caughtin4k.gateway_setup_requests (request_id, gateway_id) VALUES (%s, %s) "
            "ON CONFLICT (request_id) DO NOTHING RETURNING request_id",
            (payload.request_id, gateway_id),
        ).fetchone()
        if inserted is None:
            raise HTTPException(status_code=409, detail="This setup attempt has been superseded. Start a new attempt.")
        connection.execute(
            "INSERT INTO caughtin4k.gateway_setup "
            "(gateway_id, request_id, fingerprint, encrypted_wifi, expires_at) "
            "VALUES (%s, %s, %s, %s, now() + interval '15 minutes') "
            "ON CONFLICT (gateway_id) DO UPDATE SET request_id = excluded.request_id, "
            "fingerprint = excluded.fingerprint, encrypted_wifi = excluded.encrypted_wifi, "
            "expires_at = excluded.expires_at, error_code = NULL",
            (gateway_id, payload.request_id, fingerprint, cipher.encrypt(plain.encode("utf-8")).decode("ascii")),
        )
    return {"request_id": str(payload.request_id)}


def exchange(gateway_id: UUID, credential: str, report: SetupReport) -> dict:
    cipher = setup_cipher()
    with connect() as connection:
        gateway = _machine(connection, gateway_id, credential)
        if gateway["household_id"] is None:
            return {"paired": False, "configuration": None}
        connection.execute(
            "INSERT INTO caughtin4k.gateway_setup (gateway_id, reported_request_id, checks, error_code, received_at) "
            "VALUES (%s, %s, %s, %s, now()) ON CONFLICT (gateway_id) DO UPDATE SET "
            "reported_request_id = excluded.reported_request_id, checks = excluded.checks, "
            "error_code = excluded.error_code, received_at = now()",
            (gateway_id, report.request_id, Jsonb(report.checks), report.error_code),
        )
        row = connection.execute(
            "SELECT * FROM caughtin4k.gateway_setup WHERE gateway_id = %s", (gateway_id,),
        ).fetchone()
        if row["request_id"] is not None and report.request_id == row["request_id"] and report.error_code is None:
            # The Pi persists its applied configuration before reporting it.
            connection.execute(
                "UPDATE caughtin4k.gateway_setup SET encrypted_wifi = NULL WHERE gateway_id = %s", (gateway_id,),
            )
            return {"paired": True, "configuration": None}
        if row["encrypted_wifi"] is None:
            return {"paired": True, "configuration": None}
        if row["expires_at"] <= datetime.now(timezone.utc):
            connection.execute(
                "UPDATE caughtin4k.gateway_setup SET encrypted_wifi = NULL WHERE gateway_id = %s", (gateway_id,),
            )
            return {"paired": True, "configuration": None}
        try:
            data = json.loads(cipher.decrypt(row["encrypted_wifi"].encode("ascii")))
        except (InvalidToken, ValueError, UnicodeError):
            raise HTTPException(status_code=503, detail="Pending setup configuration cannot be decrypted.") from None
        return {"paired": True, "configuration": {
            "request_id": str(row["request_id"]), "ssid": data["ssid"], "password": data["password"],
        }}


def read_setup(account_id: UUID, home: UUID, gateway_id: UUID) -> dict:
    setup_cipher()
    with connect() as connection:
        _user(connection, account_id, home, gateway_id, manage=False)
        connection.execute(
            "UPDATE caughtin4k.gateway_setup SET encrypted_wifi = NULL "
            "WHERE gateway_id = %s AND expires_at <= now()", (gateway_id,),
        )
        row = connection.execute(
            "SELECT request_id, reported_request_id, checks, error_code, received_at, expires_at "
            "FROM caughtin4k.gateway_setup WHERE gateway_id = %s", (gateway_id,),
        ).fetchone()
    now = datetime.now(timezone.utc)
    recent = bool(row and row["received_at"] and row["received_at"] >= now - timedelta(seconds=45))
    applied = bool(row and row["request_id"] and row["request_id"] == row["reported_request_id"])
    checks = row["checks"] if row else {}
    ready = recent and applied and set(checks) == CHECKS and all(checks.values()) and row["error_code"] is None
    expired = bool(row and not applied and row["expires_at"] and row["expires_at"] <= now)
    return {
        "ready": ready, "recent_contact": recent, "configured": applied,
        "request_id": str(row["request_id"]) if row and row["request_id"] else None,
        "checks": checks, "error_code": row["error_code"] if row else None,
        "expired": expired,
    }
