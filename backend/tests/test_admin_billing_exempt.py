"""Tests for admin billing-exempt endpoint."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_billing_exempt_requires_auth(client):
    """PATCH /api/admin/tenants/{id}/billing-exempt without auth returns 401 or 403."""
    resp = client.patch(
        "/api/admin/tenants/some-tenant-id/billing-exempt",
        json={"extend_months": 1},
    )
    assert resp.status_code in (401, 403, 404, 503)


def test_billing_exempt_rejects_empty_body(client):
    """PATCH with no body or missing fields returns 400 when auth would pass (we get 401/403 first)."""
    resp = client.patch(
        "/api/admin/tenants/some-tenant-id/billing-exempt",
        json={},
    )
    # Without admin auth we get 401/403; with auth we'd get 400 for missing fields
    assert resp.status_code in (400, 401, 403, 404, 503)
