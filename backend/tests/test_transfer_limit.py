"""Tests for call transfer limit enforcement in PATCH /api/business-info."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    return TestClient(app)


def _staff_one():
    return [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "name": "Alex", "phone": "+15551234567"}]


def test_transfer_limit_returns_403_when_exceeding_plan(client, monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": _staff_one(),
                "transfer_targets": [
                    {"name": "A", "phone": "+15551111111"},
                    {"name": "B", "phone": "+15552222222"},
                ],
            },
        )
        assert resp.status_code == 403
        assert "Plan allows up to 1" in resp.json().get("detail", "")


def test_transfer_limit_accepts_within_limit(client, monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": _staff_one(),
                "transfer_targets": [{"name": "Alex", "phone": "+15551234567", "staff_id": _staff_one()[0]["id"]}],
            },
        )
        assert resp.status_code == 200


def test_staff_roster_unlimited_many_members(client, monkeypatch):
    """Many roster members allowed; transfer cap is separate."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}
    many = [{"name": f"Person {i}", "phone": ""} for i in range(25)]

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch("/api/business-info", json={"staff": many})
        assert resp.status_code == 200
        assert len(resp.json().get("staff") or []) == 25


def test_transfer_rejects_unknown_staff_id(client, monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": _staff_one(),
                "transfer_targets": [
                    {
                        "name": "Ghost",
                        "phone": "+15559999999",
                        "staff_id": "00000000-0000-0000-0000-000000000099",
                    }
                ],
            },
        )
        assert resp.status_code == 400
        assert "roster" in resp.json().get("detail", "").lower()
