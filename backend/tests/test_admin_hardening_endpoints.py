"""Auth boundary tests for new admin hardening endpoints."""
from fastapi.testclient import TestClient

from main import app


def test_admin_bulk_tenant_create_requires_auth():
    client = TestClient(app)
    resp = client.post(
        "/api/admin/tenants/bulk",
        json={"rows": [{"client_id": "x", "name": "X", "twilio_phone_number": "+15555550123", "email": "x@example.com"}]},
    )
    assert resp.status_code in (401, 403, 404, 503)


def test_admin_ops_self_check_requires_auth():
    client = TestClient(app)
    resp = client.get("/api/admin/ops/self-check")
    assert resp.status_code in (401, 403, 404, 503)


def test_admin_legal_holds_requires_auth():
    client = TestClient(app)
    list_resp = client.get("/api/admin/legal-holds")
    upsert_resp = client.post(
        "/api/admin/legal-holds",
        json={"client_id": "tenant-a", "reason": "test-hold"},
    )
    clear_resp = client.delete("/api/admin/legal-holds/tenant-a")
    assert list_resp.status_code in (401, 403, 404, 503)
    assert upsert_resp.status_code in (401, 403, 404, 503)
    assert clear_resp.status_code in (401, 403, 404, 503)
