"""Customer cloud entrypoint; no operator token is required by app or website."""

import logging
import os
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from cloud_account_api import build_router
from cloud_account_security import limit, mail_settings
from cloud_database import CloudDatabaseError
from fastapi import HTTPException
import cloud_push

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    if os.getenv("GHOST_CLOUD_CUSTOMER_ENABLED", "").lower() != "true":
        raise ValueError("Explicitly enable the customer cloud service after rollout validation.")
    secret = os.getenv("GHOST_CLOUD_SESSION_SECRET", "")
    if len(secret) < 32:
        raise ValueError("Configure the private cloud session signing secret.")
    mail_settings()
    origins = [value.strip() for value in os.getenv("GHOST_CLOUD_WEB_ORIGINS", "").split(",") if value.strip()]
    for origin in origins:
        uri = urlsplit(origin)
        if uri.scheme != "https" or not uri.hostname or "*" in origin or uri.username or uri.password or uri.query or uri.fragment or uri.path:
            raise ValueError("Configure exact HTTPS website origins, without paths or wildcards.")
    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()
        push_task = None
        if cloud_push.enabled():
            firebase = await asyncio.to_thread(cloud_push.configure)
            push_task = asyncio.create_task(cloud_push.worker(firebase, stop))
        try:
            yield
        finally:
            stop.set()
            if push_task is not None:
                await push_task

    app = FastAPI(title="caughtIn4K", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def protect_requests(request: Request, call_next):
        if request.url.path != "/health" and request.method != "OPTIONS":
            try:
                host = request.client.host if request.client else "unknown"
                auth = request.url.path.startswith("/cloud/auth/")
                await run_in_threadpool(
                    limit, f"{'auth' if auth else 'api'}:{host}", secret,
                    20 if auth else 180, 60,
                )
                if request.url.path in {"/cloud/auth/login", "/cloud/auth/signup", "/cloud/auth/reset-password"}:
                    try:
                        body = await request.json()
                    except ValueError:
                        return JSONResponse(status_code=400, content={"detail": "Invalid JSON request."})
                    email = body.get("email") if isinstance(body, dict) else None
                    if isinstance(email, str) and len(email) <= 254:
                        await run_in_threadpool(limit, "account:" + email.strip().lower(), secret, 10, 900)
            except HTTPException as error:
                return JSONResponse(status_code=error.status_code, content={"detail": error.detail},
                                    headers=error.headers)
            except CloudDatabaseError:
                logger.error("Customer request throttling storage unavailable.")
                return JSONResponse(status_code=503, content={"detail": "Account storage is unavailable."})
        return await call_next(request)

    # CORS wraps request protection so browser clients can read explicit errors.
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["Authorization", "Content-Type", "X-Gateway-Credential",
                                      "X-Cloud-Staging-Token"])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(build_router(secret, require_verified=True))
    return app


app = create_app()
