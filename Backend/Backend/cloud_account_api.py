"""Scoped cloud account/gateway API shared by private and customer entrypoints."""

from __future__ import annotations

import logging
import os
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

import cloud_accounts as accounts
import cloud_gateways as gateways
import cloud_households as households
import cloud_monitoring as monitoring
import cloud_commands as commands
import cloud_account_security as security
import cloud_push
from cloud_database import CloudDatabaseError

logger = logging.getLogger(__name__)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class SignupInput(LoginInput):
    name: str = Field(min_length=1, max_length=200)


class PairGatewayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gateway_id: UUID
    pairing_code: str = Field(min_length=1, max_length=256)
    household_name: str = Field(min_length=1, max_length=200)


class InviteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=1, max_length=254)
    role: Literal["admin", "member"] = "member"


class AcceptInviteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invite_code: str = Field(min_length=1, max_length=256)

class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=1, max_length=254)


class CodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=256)


class ResetInput(EmailInput):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=1024)


class ChangePasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


def build_router(secret: str, *, require_verified: bool = False) -> APIRouter:
    if len(secret) < 32:
        raise ValueError("Cloud account mode requires GHOST_CLOUD_SESSION_SECRET with at least 32 characters.")
    router = APIRouter(prefix="/cloud", tags=["Cloud accounts"])
    bearer = HTTPBearer(auto_error=False)

    async def operation(function, *args):
        try:
            return await run_in_threadpool(function, *args)
        except CloudDatabaseError:
            logger.error("Cloud account database operation failed.")
            raise HTTPException(status_code=503, detail="Cloud account storage is unavailable.") from None

    async def current_session(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        header = f"Bearer {credentials.credentials}" if credentials else ""
        return await operation(accounts.authenticate, header, secret)

    async def current_account(account=Depends(current_session)):
        if require_verified and account.get("email_verified_at") is None:
            raise HTTPException(status_code=403, detail="Verify your email before accessing a home.")
        return account

    def session_result(account):
        return {
            **accounts.public_account(account),
            "access_token": accounts.issue_token(account, secret),
            "token_type": "bearer",
            "expires_in": accounts.SESSION_SECONDS,
        }

    @router.post("/auth/signup", status_code=201)
    async def signup(payload: SignupInput):
        account = await operation(accounts.create_account, payload.name, payload.email, payload.password)
        return session_result(account)

    @router.post("/auth/login")
    async def login(payload: LoginInput):
        account = await operation(accounts.login, payload.email, payload.password)
        return session_result(account)

    @router.get("/auth/me")
    async def me(account=Depends(current_session)):
        return accounts.public_account(account)

    @router.post("/auth/request-password-reset")
    async def request_reset(payload: EmailInput):
        await operation(security.limit, "reset:" + payload.email.strip().lower(), secret, 3, 900)
        return await operation(security.request_reset, payload.email)

    @router.post("/auth/reset-password")
    async def reset_password(payload: ResetInput):
        return await operation(security.reset_password, payload.email, payload.token, payload.new_password)

    @router.post("/auth/change-password")
    async def change_password(payload: ChangePasswordInput, account=Depends(current_account)):
        return await operation(security.change_password, account["id"], payload.current_password, payload.new_password)

    @router.post("/auth/request-verification")
    async def request_verification(account=Depends(current_session)):
        await operation(security.limit, "verify:" + str(account["id"]), secret, 3, 900)
        return await operation(security.send_verification, account["id"])

    @router.post("/auth/verify-email")
    async def verify_email(payload: CodeInput, account=Depends(current_session)):
        return await operation(security.verify_email, account["id"], payload.token)

    @router.post("/auth/logout-all")
    async def logout_all(account=Depends(current_account)):
        await operation(accounts.revoke_sessions, account["id"])
        return {"success": True}

    @router.get("/households")
    async def list_households(account=Depends(current_account)):
        rows = await operation(accounts.memberships, account["id"])
        return {"households": rows}

    @router.post("/push/register")
    async def register_push(payload: cloud_push.RegistrationInput, account=Depends(current_account)):
        return await operation(cloud_push.register, account, payload)

    @router.post("/push/unregister")
    async def unregister_push(payload: cloud_push.InstallationInput):
        return await operation(cloud_push.unregister, payload)

    @router.post("/gateways/pair", status_code=201)
    async def pair_gateway(payload: PairGatewayInput, account=Depends(current_account)):
        return await operation(
            gateways.pair_gateway, account["id"], payload.gateway_id,
            payload.pairing_code, payload.household_name,
        )

    @router.get("/households/{household_id}/gateways")
    async def list_gateways(household_id: UUID, account=Depends(current_account)):
        rows = await operation(gateways.list_gateways, account["id"], household_id)
        return {"gateways": rows}

    @router.post("/households/{household_id}/invites", status_code=201)
    async def invite(household_id: UUID, payload: InviteInput, account=Depends(current_account)):
        return await operation(
            households.create_invite, account["id"], household_id, payload.email, payload.role,
        )

    @router.post("/household-invites/accept")
    async def accept_invite(payload: AcceptInviteInput, account=Depends(current_account)):
        return await operation(households.accept_invite, account["id"], payload.invite_code)

    @router.put("/gateways/{gateway_id}/snapshot")
    async def upload_snapshot(
        gateway_id: UUID, payload: monitoring.MonitoringSnapshot,
        credential: str = Header(default="", alias="X-Gateway-Credential", max_length=256),
    ):
        return await operation(monitoring.upload_snapshot, gateway_id, credential, payload)

    @router.get("/households/{household_id}/gateways/{gateway_id}/snapshot")
    async def snapshot(household_id: UUID, gateway_id: UUID, account=Depends(current_account)):
        result = await operation(monitoring.read_snapshot, account["id"], household_id, gateway_id)
        return {**result, "device_management_available": os.getenv("GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED", "").lower() == "true"}

    @router.post("/households/{household_id}/gateways/{gateway_id}/commands", status_code=202)
    async def create_command(
        household_id: UUID, gateway_id: UUID, payload: commands.CommandInput,
        account=Depends(current_account),
    ):
        return await operation(commands.create_command, account["id"], household_id, gateway_id, payload)

    @router.get("/households/{household_id}/gateways/{gateway_id}/commands/{command_id}")
    async def command_status(
        household_id: UUID, gateway_id: UUID, command_id: UUID, account=Depends(current_account),
    ):
        return await operation(commands.read_command, account["id"], household_id, gateway_id, command_id)

    @router.post("/gateways/{gateway_id}/commands/next")
    async def next_command(
        gateway_id: UUID,
        credential: str = Header(default="", alias="X-Gateway-Credential", max_length=256),
    ):
        return await operation(commands.take_command, gateway_id, credential)

    @router.put("/gateways/{gateway_id}/commands/{command_id}/result")
    async def command_result(
        gateway_id: UUID, command_id: UUID, payload: commands.CommandResult,
        credential: str = Header(default="", alias="X-Gateway-Credential", max_length=256),
    ):
        return await operation(commands.complete_command, gateway_id, credential, command_id, payload)

    return router
