"""HTTP security response headers for the FastAPI backend."""

from __future__ import annotations

import os
from typing import MutableMapping

from starlette.requests import Request
from starlette.responses import Response

from twilio_provision import validate_public_base_url

HSTS_VALUE = "max-age=63072000; includeSubDomains; preload"

# This service is a pure JSON/XML/audio API — it never returns browser-rendered
# HTML, so the tightest possible CSP is safe and blocks the API from being abused
# as a script/content-injection vector. Swagger UI at /docs needs inline scripts,
# so the policy is skipped there (see apply_security_headers).
API_CSP_VALUE = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")

BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-DNS-Prefetch-Control": "off",
}


def request_is_https(request: Request) -> bool:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded:
        return forwarded == "https"
    return request.url.scheme == "https"


def should_send_hsts(request: Request) -> bool:
    if not request_is_https(request):
        return False
    public_base = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    origin, errors = validate_public_base_url(public_base)
    return bool(origin) and not errors


def _set_if_missing(headers: MutableMapping[str, str], key: str, value: str) -> None:
    existing = headers.get(key)
    if existing is None:
        headers[key] = value


def apply_security_headers(response: Response, *, request: Request) -> None:
    """Add security headers without overwriting handler-specific values."""
    for key, value in BASE_HEADERS.items():
        _set_if_missing(response.headers, key, value)

    if should_send_hsts(request):
        _set_if_missing(response.headers, "Strict-Transport-Security", HSTS_VALUE)

    if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
        _set_if_missing(response.headers, "Content-Security-Policy", API_CSP_VALUE)

    if request.url.path.startswith("/api/admin/"):
        _set_if_missing(response.headers, "Cache-Control", "no-store")

    server_key = next((k for k in response.headers.keys() if k.lower() == "server"), None)
    if server_key is not None:
        del response.headers[server_key]
