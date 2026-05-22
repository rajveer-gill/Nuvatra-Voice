"""Tests for team roster saves via PATCH /api/business-info (legacy transfer_targets ignored)."""
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


def test_transfer_targets_in_payload_are_ignored(client, monkeypatch):
    """Call transfers use team roster only; separate transfer_targets are not stored."""
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
        assert resp.status_code == 200
        body = resp.json()
        assert not body.get("transfer_targets")


def test_staff_save_with_phone_succeeds(client, monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch(
            "/api/business-info",
            json={"staff": _staff_one()},
        )
        assert resp.status_code == 200
        assert len(resp.json().get("staff") or []) == 1


def test_staff_roster_unlimited_many_members(client, monkeypatch):
    """Many roster members allowed."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}
    many = [{"name": f"Person {i}", "phone": ""} for i in range(25)]

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch("/api/business-info", json={"staff": many})
        assert resp.status_code == 200
        assert len(resp.json().get("staff") or []) == 25
