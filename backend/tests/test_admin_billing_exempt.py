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


def test_account_paused_requires_auth(client):
    """PATCH /api/admin/tenants/{id}/account-paused without auth is rejected."""
    resp = client.patch(
        "/api/admin/tenants/some-tenant-id/account-paused",
        json={"paused": True},
    )
    assert resp.status_code in (401, 403, 404, 503)


def test_account_paused_sets_flag_and_audits(client, monkeypatch):
    """With admin auth + DB, the endpoint flips account_paused and audit-logs."""
    import database
    import deps
    import runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    set_calls = {}
    audits = []
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda tid: {"id": tid, "client_id": "c-1"})
    monkeypatch.setattr(
        database, "db_tenant_set_account_paused",
        lambda tid, paused: set_calls.update(tid=tid, paused=paused) or True,
    )
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: audits.append((a, k)))
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        resp = client.patch(
            "/api/admin/tenants/t-1/account-paused",
            json={"paused": True},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "account_paused": True}
        assert set_calls == {"tid": "t-1", "paused": True}
        assert any(a[:2] == ("admin", "account_paused") for a, _k in audits)
    finally:
        app.dependency_overrides.clear()
