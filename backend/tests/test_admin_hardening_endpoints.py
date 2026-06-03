"""Auth boundary tests for new admin hardening endpoints."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app, require_admin


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


def test_admin_ops_self_check_includes_redis_fields():
    app.dependency_overrides[require_admin] = lambda: "admin-test-user"
    fake_redis = {
        "redis_url_set": True,
        "redis_url_scheme_ok": True,
        "redis_ping_ok": True,
        "voice_state_backend": "redis",
        "redis_config_consistent": True,
        "redis_host_looks_external": False,
        "redis_production_ready": True,
    }
    try:
        client = TestClient(app)
        with patch("voice.redis_ops_health.redis_ops_health", return_value=fake_redis):
            resp = client.get("/api/admin/ops/self-check")
        assert resp.status_code == 200
        body = resp.json()
        for key in fake_redis:
            assert body[key] == fake_redis[key]
    finally:
        app.dependency_overrides.clear()


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
