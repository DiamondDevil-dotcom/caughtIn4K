"""Private cloud staging, independent of legacy inference and Flower startup."""

import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cloud_account_api import build_router


def create_app() -> FastAPI:
    staging_token = os.getenv("GHOST_CLOUD_STAGING_TOKEN", "")
    if len(staging_token) < 32:
        raise ValueError("Configure a private GHOST_CLOUD_STAGING_TOKEN of at least 32 characters.")
    app = FastAPI(title="caughtIn4K private cloud staging", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.middleware("http")
    async def private_access(request: Request, call_next):
        if request.url.path != "/health" and not hmac.compare_digest(
            request.headers.get("X-Cloud-Staging-Token", "").encode(), staging_token.encode(),
        ):
            return JSONResponse(status_code=401, content={"detail": "Private cloud staging access required."})
        return await call_next(request)

    @app.get("/health")
    def health():
        # Process readiness only; database operations report their own failures.
        return {"status": "ok"}

    app.include_router(build_router(os.getenv("GHOST_CLOUD_SESSION_SECRET", "")))
    return app


app = create_app()
