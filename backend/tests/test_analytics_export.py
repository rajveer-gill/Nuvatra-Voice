"""Tests for analytics export API and plan gating."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    return TestClient(app)


def test_analytics_export_starter_returns_403(client):
    """GET /api/analytics/export on Starter plan returns 403."""
    # Single-tenant: tenant is None -> get_plan_limits(None) returns starter limits
    # Starter has has_export=False
    resp = client.get("/api/analytics/export")
    assert resp.status_code == 403
    data = resp.json()
    assert "Export" in data.get("detail", "") or "Growth" in data.get("detail", "") or "Pro" in data.get("detail", "")


def _tenant_growth():
    return {"plan": "growth", "client_id": "test-spa", "id": "123", "subscription_status": "active"}


def _tenant_pro():
    return {"plan": "pro", "client_id": "test-spa", "id": "123", "subscription_status": "active"}


def test_analytics_export_growth_returns_csv(client):
    """GET /api/analytics/export on Growth plan returns CSV."""
    from main import require_tenant
    app.dependency_overrides[require_tenant] = _tenant_growth

    with patch("main._load_call_log", return_value=[]):
        try:
            resp = client.get("/api/analytics/export")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.pop(require_tenant, None)


def test_analytics_export_pro_returns_csv(client):
    """GET /api/analytics/export on Pro plan returns CSV."""
    from main import require_tenant
    app.dependency_overrides[require_tenant] = _tenant_pro

    with patch("main._load_call_log", return_value=[]):
        try:
            resp = client.get("/api/analytics/export")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.pop(require_tenant, None)
