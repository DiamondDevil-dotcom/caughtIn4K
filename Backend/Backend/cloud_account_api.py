"""Development-only cloud API. No endpoint delegates to the legacy Pi."""

from __future__ import annotations

import logging
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


def build_router(secret: str) -> APIRouter:
    if len(secret) < 32:
        raise ValueError("Cloud account mode requires GHOST_CLOUD_SESSION_SECRET with at least 32 characters.")
    router = APIRouter(prefix="/cloud", tags=["Cloud account development"])
    bearer = HTTPBearer(auto_error=False)

    async def operation(function, *args):
        try:
            return await run_in_threadpool(function, *args)
        except CloudDatabaseError:
            logger.error("Cloud account database operation failed.")
            raise HTTPException(status_code=503, detail="Cloud account storage is unavailable.") from None

    async def current_account(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        header = f"Bearer {credentials.credentials}" if credentials else ""
        return await operation(accounts.authenticate, header, secret)

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
    async def me(account=Depends(current_account)):
        return accounts.public_account(account)

    @router.post("/auth/logout-all")
    async def logout_all(account=Depends(current_account)):
        await operation(accounts.revoke_sessions, account["id"])
        return {"success": True}

    @router.get("/households")
    async def list_households(account=Depends(current_account)):
        rows = await operation(accounts.memberships, account["id"])
        return {"households": rows}

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
        return await operation(monitoring.read_snapshot, account["id"], household_id, gateway_id)

    return router
