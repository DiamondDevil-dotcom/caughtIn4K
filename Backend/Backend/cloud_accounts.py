"""Cloud accounts have their own token namespace, separate from legacy Pi sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from cloud_database import connect

PASSWORD_ITERATIONS = 600_000
SESSION_SECONDS = 3600
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return value


def validate_password(password: str) -> None:
    if not 8 <= len(password) <= 1024:
        raise HTTPException(status_code=400, detail="Use a password between 8 and 1024 characters.")


def password_hash(password: str, salt: bytes, iterations: int = PASSWORD_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def public_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "account_id": str(account["id"]),
        "email": account["email"],
        "name": account["name"],
        "email_verified": account.get("email_verified_at") is not None,
    }


def create_account(name: str, email: str, password: str) -> dict[str, Any]:
    email = normalize_email(email)
    name = name.strip()
    if not name or len(name) > 200:
        raise HTTPException(status_code=400, detail="Use a name between 1 and 200 characters.")
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = password_hash(password, salt)
    with connect() as connection:
        account = connection.execute(
            "INSERT INTO caughtin4k.accounts "
            "(id, email, name, password_hash, password_salt, password_algorithm, password_iterations) "
            "VALUES (%s, %s, %s, %s, %s, 'pbkdf2_sha256', %s) "
            "ON CONFLICT (email) DO NOTHING "
            "RETURNING id, email, name, session_version, email_verified_at",
            (uuid4(), email, name, digest, salt.hex(), PASSWORD_ITERATIONS),
        ).fetchone()
        if account is None:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return account


def login(email: str, password: str) -> dict[str, Any]:
    email = normalize_email(email)
    if not password or len(password) > 1024:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    with connect() as connection:
        account = connection.execute(
            "SELECT id, email, name, password_hash, password_salt, password_algorithm, "
            "password_iterations, session_version, email_verified_at FROM caughtin4k.accounts WHERE email = %s",
            (email,),
        ).fetchone()
    # Missing accounts still do the expensive work; responses do not identify which field failed.
    salt = bytes.fromhex(account["password_salt"]) if account else bytes(16)
    iterations = account["password_iterations"] if account else PASSWORD_ITERATIONS
    candidate = password_hash(password, salt, iterations)
    if account is None or not hmac.compare_digest(candidate, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return account


def issue_token(account: dict[str, Any], secret: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": str(account["id"]),
        "version": account["session_version"],
        "exp": int(time.time()) + SESSION_SECONDS,
        "nonce": secrets.token_hex(16),
    }, separators=(",", ":")).encode()).decode()
    message = f"cloud-v1.{payload}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}.{signature}"


def authenticate(header: str, secret: str) -> dict[str, Any]:
    try:
        if not header.startswith("Bearer ") or len(header) > 4096:
            raise ValueError("Missing token")
        namespace, payload, signature = header[7:].split(".")
        if namespace != "cloud-v1":
            raise ValueError("Wrong namespace")
        expected = hmac.new(secret.encode(), f"{namespace}.{payload}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid signature")
        data = json.loads(base64.b64decode(payload, altchars=b"-_", validate=True))
        if not isinstance(data, dict):
            raise ValueError("Invalid payload")
        if type(data["exp"]) is not int or data["exp"] <= time.time():
            raise ValueError("Expired token")
        if type(data["version"]) is not int or data["version"] < 0:
            raise ValueError("Invalid version")
        account_id = UUID(data["sub"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(status_code=401, detail="Cloud session expired or invalid. Sign in again.") from None
    with connect() as connection:
        account = connection.execute(
            "SELECT id, email, name, session_version, email_verified_at FROM caughtin4k.accounts WHERE id = %s",
            (account_id,),
        ).fetchone()
    if account is None or account["session_version"] != data["version"]:
        raise HTTPException(status_code=401, detail="Cloud session revoked. Sign in again.")
    return account


def memberships(account_id: UUID) -> list[dict[str, Any]]:
    with connect() as connection:
        return connection.execute(
            "SELECT h.id AS household_id, h.name, m.role "
            "FROM caughtin4k.household_members m "
            "JOIN caughtin4k.households h ON h.id = m.household_id "
            "WHERE m.account_id = %s ORDER BY h.created_at, h.id",
            (account_id,),
        ).fetchall()


def revoke_sessions(account_id: UUID) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE caughtin4k.accounts SET session_version = session_version + 1 WHERE id = %s",
            (account_id,),
        )
