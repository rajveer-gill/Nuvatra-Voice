"""Gated /sentry-debug route — must not be public in production by default."""

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client_no_raise():
    """500 responses are returned, not raised (matches prod HTTP semantics)."""
    return TestClient(app, raise_server_exceptions=False)


def test_sentry_debug_returns_404_when_disabled(client):
    """Default: no ENABLE flag, no SENTRY_DEBUG_SECRET in test env -> 404."""
    resp = client.get("/sentry-debug")
    assert resp.status_code == 404


def test_sentry_debug_fires_with_enable_flag(client_no_raise, monkeypatch):
    monkeypatch.setenv("ENABLE_SENTRY_DEBUG_ROUTE", "true")
    resp = client_no_raise.get("/sentry-debug")
    assert resp.status_code == 500


def test_sentry_debug_fires_with_secret_header(client_no_raise, monkeypatch):
    monkeypatch.setenv("SENTRY_DEBUG_SECRET", "test-secret-value")
    resp = client_no_raise.get("/sentry-debug", headers={"X-Sentry-Debug-Secret": "test-secret-value"})
    assert resp.status_code == 500


def test_sentry_debug_wrong_secret_404(client, monkeypatch):
    monkeypatch.setenv("SENTRY_DEBUG_SECRET", "correct")
    resp = client.get("/sentry-debug", headers={"X-Sentry-Debug-Secret": "wrong"})
    assert resp.status_code == 404
