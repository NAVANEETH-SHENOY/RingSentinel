"""FastAPI application factory (component C11).

Run:  python scripts\run_api.py        (or: uvicorn --factory app.main:create_app --app-dir backend)
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.audit import AuditLog
from app.config import AppSettings, load_app_settings
from app.ratelimit import RateLimiter
from app.routes import router
from app.store import SnapshotStore

API_VERSION = "0.5.0"


def create_app(settings: AppSettings | None = None, *, clock=None) -> FastAPI:
    """Build the app. Fails fast if the snapshot bundle is missing, invalid or tampered with."""
    settings = settings or load_app_settings()
    store = SnapshotStore(settings.snapshot_dir)
    audit = AuditLog(settings.audit_db_url)
    limiter_args = {
        "read": settings.rate_limit_read_per_min, "write": settings.rate_limit_write_per_min,
    }  # fmt: skip
    limiter = RateLimiter(limiter_args, clock) if clock else RateLimiter(limiter_args)

    app = FastAPI(title="RingSentinel API", version=API_VERSION, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")  # fmt: skip
    app.state.settings, app.state.store, app.state.audit = settings, store, audit
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Analyst-Token"],
    )  # fmt: skip

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        bucket = "write" if request.method == "POST" else "read"
        client = request.client.host if request.client else "unknown"
        wait = limiter.check(client, bucket)
        if wait is not None:
            return JSONResponse(
                {"detail": "rate limit exceeded"}, status_code=429,
                headers={"Retry-After": str(int(wait) + 1)},
            )  # fmt: skip
        return await call_next(request)

    app.include_router(router)
    return app
