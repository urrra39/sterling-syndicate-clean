from __future__ import annotations

"""The Sterling Syndicate FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import (
    analytics,
    auth,
    browser_guard_api,
    contracts,
    conversations,
    dlq_api,
    execution,
    health,
    leads,
    portfolio,
    proposals,
)
from app.core.config import get_settings, settings
from app.core.database import ensure_schema, init_engine, using_sqlite
from app.core.rate_limit import client_key, rate_limit
from app.middleware.output_sanitizer_middleware import OutputSanitizerMiddleware
from app.services.dlq import start_dlq_worker, stop_dlq_worker
from app.services.dlq_handlers import register_all_handlers
from app.services.followup import start_followup_scheduler, stop_followup_scheduler
from app.services.scout_scheduler import start_scout_scheduler, stop_scout_scheduler

logger = logging.getLogger("sterling_syndicate")

# Strict transport / MIME-sniffing / clickjacking protections applied to EVERY
# response, including error (500) and rate-limit (429) responses.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

# Global per-client request budget. Complements the tighter per-endpoint limits
# already enforced inside individual routers (which use their own bucket keys).
GLOBAL_RATE_LIMIT = 120
GLOBAL_RATE_WINDOW_SECONDS = 60


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject strict security headers on all outgoing responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply the existing in-memory rate limiter to standard API endpoints.
    /health (liveness/readiness probes) is always exempt, and CORS preflight
    (OPTIONS) requests are never counted.
    """

    def __init__(self, app, *, limit: int, window_seconds: int) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path == "/health" or path.startswith("/health/"):
            return await call_next(request)

        try:
            rate_limit(
                client_key(request, "global"),
                limit=self.limit,
                window_seconds=self.window_seconds,
            )
        except HTTPException as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
            for header, value in SECURITY_HEADERS.items():
                response.headers[header] = value
            return response

        return await call_next(request)


class CsrfGuardMiddleware(BaseHTTPMiddleware):
    """Require a custom header for cookie-authenticated mutating requests.

    Browsers do not attach arbitrary headers on classic cross-site form posts,
    so ``X-Requested-With: XMLHttpRequest`` blocks simple CSRF against the
    HttpOnly session cookie. Bearer Authorization remains CSRF-resistant on its
    own. HMAC payment webhooks and health probes are exempt. Disabled under
    TESTING so pytest TestClient stays lightweight.
    """

    async def dispatch(self, request: Request, call_next):
        if settings.testing or settings.environment.lower() == "test":
            return await call_next(request)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        path = request.url.path
        if path == "/health" or path.startswith("/health/"):
            return await call_next(request)
        if path.endswith("/payment-webhook"):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and len(auth) > 8:
            return await call_next(request)
        if request.headers.get("x-requested-with", "").lower() == "xmlhttprequest":
            return await call_next(request)
        response = JSONResponse(
            status_code=403,
            content={"detail": "Missing CSRF header (X-Requested-With)."},
        )
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings.cache_clear()
    init_engine()
    ensure_schema()
    register_all_handlers()
    if settings.environment.lower() != "test":
        start_scout_scheduler()
        start_dlq_worker()
        start_followup_scheduler()
    try:
        yield
    finally:
        stop_scout_scheduler()
        stop_dlq_worker()
        stop_followup_scheduler()


app = FastAPI(
    title="The Sterling Syndicate API",
    description=(
        "Elite autonomous executive agency. "
        "Multi-agent drafts with RAG — human-in-the-loop, never auto-sends. "
        "No marketplace login automation. Docker-free SQLite fallback supported."
    ),
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    # With allow_credentials=True a wildcard is both a spec violation (browsers
    # reject "*" + credentials) and a security hole. Enumerate exactly what the
    # SPA needs.
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
    ],
    expose_headers=["Content-Type", "Content-Length"],
    max_age=600,
)

# Last-hop scrub: strip <<<UNTRUSTED_*>>> / <system> leaks from JSON bodies
app.add_middleware(OutputSanitizerMiddleware)

# CSRF (cookie sessions) → rate limit → security headers (outermost) so 403/429/500
# responses still carry HSTS / frame / MIME protections.
app.add_middleware(CsrfGuardMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    limit=GLOBAL_RATE_LIMIT,
    window_seconds=GLOBAL_RATE_WINDOW_SECONDS,
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global 500 masking.
    Log the full exception server-side (with traceback via exc_info) and return a
    safe, generic JSON body. Stack traces are NEVER sent to the client. This runs
    in Starlette's outermost error middleware, so it sets the security headers itself.
    """
    logger.error(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal system error. The incident has been logged."},
    )
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(leads.router, prefix="/leads", tags=["leads"])
app.include_router(proposals.router, tags=["proposals"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(contracts.router, tags=["contracts"])
app.include_router(execution.router, tags=["execution"])
app.include_router(browser_guard_api.router)
app.include_router(dlq_api.router, tags=["dlq"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])

@app.get("/")
def root() -> dict:
    return {
        "service": "sterling-syndicate-api",
        "version": "0.5.0",
        "database": "sqlite" if using_sqlite() else "postgresql",
        "docs": "/docs",
    }
