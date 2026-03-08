"""Tests for staff limit enforcement in PATCH /api/business-info."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_staff_limit_returns_403_when_exceeding_plan(client, monkeypatch):
    """PATCH /api/business-info with staff exceeding plan limit returns 403."""
    # Use test-spa which has existing config.json
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [
                    {"name": "Staff One", "phone": "+15551234567"},
                    {"name": "Staff Two", "phone": "+15559876543"},
                ],
            },
        )
        # Starter allows 1 staff; we sent 2 -> 403
        assert resp.status_code == 403
        data = resp.json()
        assert "Plan allows up to 1" in data.get("detail", "")


def test_staff_limit_accepts_within_limit(client, monkeypatch):
    """PATCH /api/business-info with staff within plan limit succeeds."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant):
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [{"name": "Single Staff", "phone": "+15551234567"}],
            },
        )
        # Starter allows 1 staff; we sent 1 -> should succeed (200)
        assert resp.status_code == 200


def test_staff_limit_pro_allows_more(client, monkeypatch):
    """PATCH /api/business-info with many staff on Pro plan succeeds."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    pro_tenant = {"plan": "pro", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=pro_tenant):
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [
                    {"name": "A", "phone": "+15551111111"},
                    {"name": "B", "phone": "+15552222222"},
                    {"name": "C", "phone": "+15553333333"},
                ],
            },
        )
        # Pro allows 999 staff; 3 is fine
        assert resp.status_code == 200
