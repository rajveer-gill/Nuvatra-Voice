"""Security header middleware tests."""

from unittest.mock import patch

import pytest
import deps
from fastapi import Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from main import app, require_admin
from security.http_headers import apply_security_headers, should_send_hsts


def test_health_includes_base_security_headers():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"
    assert resp.headers.get("X-DNS-Prefetch-Control") == "off"
    assert resp.headers.get("X-Request-ID")
    assert (
        resp.headers.get("Content-Security-Policy")
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


def test_csp_skipped_on_swagger_docs():
    # Swagger UI needs inline scripts; a default-src 'none' CSP would break it.
    client = TestClient(app)
    resp = client.get("/docs")
    assert "Content-Security-Policy" not in resp.headers


def test_hsts_absent_on_http_request(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nuvatra-voice.onrender.com")
    client = TestClient(app)
    resp = client.get("/api/health")
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_present_on_https_request(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nuvatra-voice.onrender.com")
    client = TestClient(app, headers={"X-Forwarded-Proto": "https"})
    resp = client.get("/api/health")
    assert resp.headers.get("Strict-Transport-Security", "").startswith("max-age=")


def test_admin_path_gets_cache_control_no_store(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: "admin-test-user"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nuvatra-voice.onrender.com")
    try:
        client = TestClient(app, headers={"X-Forwarded-Proto": "https"})
        resp = client.get("/api/admin/ops/self-check")
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "no-store"
    finally:
        app.dependency_overrides.clear()


def test_cors_preflight_includes_security_headers():
    client = TestClient(app)
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_twilio_status_403_includes_security_headers(monkeypatch):
    monkeypatch.setattr("deps._validate_twilio_webhook", lambda req, data: False)
    client = TestClient(app)
    resp = client.post("/api/phone/status", data={"CallSid": "CAx", "CallStatus": "completed"})
    assert resp.status_code == 403
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_apply_security_headers_strips_server_header():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "root_path": "",
    }
    request = Request(scope)
    response = Response(content="ok", headers={"Server": "uvicorn"})
    apply_security_headers(response, request=request)
    assert not any(k.lower() == "server" for k in response.headers.keys())


def test_should_send_hsts_requires_https_request_and_public_base(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    http_scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "root_path": "",
    }
    https_scope = {**http_scope, "scheme": "https", "headers": [(b"x-forwarded-proto", b"https")]}
    assert should_send_hsts(Request(http_scope)) is False
    assert should_send_hsts(Request(https_scope)) is True
