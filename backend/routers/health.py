"""Root, health-check, and (gated) Sentry-debug endpoints."""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import database
import runtime

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Call Surge API", "status": "running"}


@router.get("/api/health")
async def health():
    """Health check for load balancers and monitoring. Returns 503 when DB is required but unreachable."""
    db_ok = (
        "ok"
        if (runtime.USE_DB and database.db_ping())
        else ("error" if runtime.USE_DB else "n/a")
    )
    if runtime.USE_DB and db_ok == "error":
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": db_ok},
        )
    return {"status": "ok", "database": db_ok}


def _sentry_debug_allowed(request: Request) -> bool:
    """Do not expose a public crash endpoint in production. Opt-in via env or shared secret header."""
    if (os.getenv("ENABLE_SENTRY_DEBUG_ROUTE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    secret = (os.getenv("SENTRY_DEBUG_SECRET") or "").strip()
    if secret:
        got = (request.headers.get("X-Sentry-Debug-Secret") or "").strip()
        if not got:
            return False
        try:
            return secrets.compare_digest(secret, got)
        except Exception:
            return False
    return False


@router.get("/sentry-debug")
async def trigger_sentry_error(request: Request):
    if not _sentry_debug_allowed(request):
        raise HTTPException(status_code=404, detail="Not Found")
    _ = 1 / 0  # intentional test error for Sentry when route is enabled
