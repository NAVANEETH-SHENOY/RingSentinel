"""FastAPI application factory (component C11).

Run:  python scripts\run_api.py        (or: uvicorn --factory app.main:create_app --app-dir backend)
"""

from __future__ import annotations

import ipaddress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.audit import AuditUnavailable, open_audit_log
from app.config import AppSettings, load_app_settings
from app.ratelimit import RateLimiter
from app.routes import router
from app.store import SnapshotStore

API_VERSION = "1.0.0"
BODY_METHODS = {"POST", "PUT", "PATCH"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def client_address(request: Request, trusted_hops: int) -> str:
    """The address rate limits are counted against.

    With no trusted proxy the socket peer is used and X-Forwarded-For is ignored (a client can
    write anything in it). With N trusted proxies the Nth entry from the RIGHT is used: each
    trusted proxy appends the address it saw, so entries to the left of that were supplied by the
    client and cannot be trusted. Anything that is not an IP address falls back to the peer.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) < trusted_hops:
        return peer
    candidate = parts[-trusted_hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer


def create_app(settings: AppSettings | None = None, *, clock=None) -> FastAPI:
    """Build the app. Fails fast if the snapshot bundle is missing, invalid or tampered with."""
    settings = settings or load_app_settings()
    store = SnapshotStore(settings.snapshot_dir)
    audit = open_audit_log(settings.audit_db_url)
    limiter_args = {
        "read": settings.rate_limit_read_per_min, "write": settings.rate_limit_write_per_min,
        "authfail": settings.rate_limit_authfail_per_min,
    }  # fmt: skip
    limiter = RateLimiter(limiter_args, clock) if clock else RateLimiter(limiter_args)

    app = FastAPI(
        title="RingSentinel API", version=API_VERSION,
        docs_url="/api/docs" if settings.docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )  # fmt: skip
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
        client = client_address(request, settings.trusted_proxy_hops)
        wait = limiter.blocked(client, "authfail") or limiter.check(client, bucket)
        if wait is not None:
            return JSONResponse(
                {"detail": "rate limit exceeded"}, status_code=429,
                headers={"Retry-After": str(int(wait) + 1)},
            )  # fmt: skip
        response = await call_next(request)
        if response.status_code == 401:
            limiter.record(client, "authfail")
        return response

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        """Refuse oversized or length-less request bodies before any route reads them."""
        if request.method in BODY_METHODS:
            if "chunked" in request.headers.get("transfer-encoding", "").lower():
                return JSONResponse({"detail": "chunked request bodies are not accepted"}, 411)
            length = request.headers.get("content-length")
            if length is not None and not length.isdigit():
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            if length is not None and int(length) > settings.max_body_bytes:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.method != "GET" or request.url.path.startswith("/api/v1/audit"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(AuditUnavailable)
    async def audit_unavailable(request: Request, exc: AuditUnavailable):
        """A hosted Postgres can be asleep or down. Say so (503) instead of a generic 500; the
        read-only snapshot path in the frontend does not depend on it."""
        return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": "5"})

    app.include_router(router)
    return app
