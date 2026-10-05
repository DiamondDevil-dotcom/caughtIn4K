"""Email-bound invitations never create accounts or replace existing roles."""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from cloud_accounts import normalize_email
from cloud_database import connect
from cloud_gateways import secret_hash


def can_invite(inviter_role: str, invited_role: str) -> bool:
    return inviter_role == "owner" or (inviter_role == "admin" and invited_role == "member")


def create_invite(
    account_id: UUID, household_id: UUID, email: str, role: str,
) -> dict[str, Any]:
    email = normalize_email(email)
    if role not in {"admin", "member"}:
        raise HTTPException(status_code=400, detail="Invite an admin or member, not an owner.")
    code = secrets.token_urlsafe(32)
    with connect() as connection:
        inviter = connection.execute(
            "SELECT role FROM caughtin4k.household_members "
            "WHERE household_id = %s AND account_id = %s FOR SHARE",
            (household_id, account_id),
        ).fetchone()
        if inviter is None:
            raise HTTPException(status_code=404, detail="Household not found.")
        if not can_invite(inviter["role"], role):
            raise HTTPException(status_code=403, detail="Your household role cannot create this invitation.")
        existing = connection.execute(
            "SELECT 1 FROM caughtin4k.household_members m "
            "JOIN caughtin4k.accounts a ON a.id = m.account_id "
            "WHERE m.household_id = %s AND a.email = %s",
            (household_id, email),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="This account is already a household member.")
        invitation = connection.execute(
            "INSERT INTO caughtin4k.household_invites "
            "(token_hash, household_id, email, role, created_by, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, now() + interval '24 hours') RETURNING expires_at",
            (secret_hash(code), household_id, email, role, account_id),
        ).fetchone()
    return {
        "success": True, "household_id": str(household_id), "email": email,
        "role": role, "invite_code": code, "expires_at": invitation["expires_at"],
    }


def accept_invite(account_id: UUID, code: str) -> dict[str, Any]:
    code = code.strip()
    if not 1 <= len(code) <= 256:
        raise HTTPException(status_code=400, detail="Household invitation is invalid or unavailable.")
    digest = secret_hash(code)
    with connect() as connection:
        invitation = connection.execute(
            "SELECT i.household_id, i.role, i.created_by "
            "FROM caughtin4k.household_invites i "
            "JOIN caughtin4k.accounts a ON a.email = i.email "
            "WHERE i.token_hash = %s AND i.expires_at > now() AND a.id = %s FOR UPDATE OF i",
            (digest, account_id),
        ).fetchone()
        if invitation is None:
            raise HTTPException(status_code=400, detail="Household invitation is invalid or unavailable.")
        household_id = invitation["household_id"]
        inviter = connection.execute(
            "SELECT role FROM caughtin4k.household_members "
            "WHERE household_id = %s AND account_id = %s FOR SHARE",
            (household_id, invitation["created_by"]),
        ).fetchone()
        if inviter is None or not can_invite(inviter["role"], invitation["role"]):
            raise HTTPException(status_code=400, detail="Household invitation is invalid or unavailable.")
        membership = connection.execute(
            "INSERT INTO caughtin4k.household_members (household_id, account_id, role) "
            "VALUES (%s, %s, %s) ON CONFLICT (household_id, account_id) DO NOTHING RETURNING role",
            (household_id, account_id, invitation["role"]),
        ).fetchone()
        if membership is None:
            raise HTTPException(status_code=409, detail="This account is already a household member.")
        connection.execute(
            "DELETE FROM caughtin4k.household_invites WHERE token_hash = %s", (digest,),
        )
    return {
        "success": True, "household_id": str(household_id), "household_role": membership["role"],
    }
