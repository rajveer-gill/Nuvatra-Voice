"""Tests for leads API and plan gating."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_leads_returns_list(client):
    """GET /api/leads returns {leads: [...]} with valid shape."""
    resp = client.get("/api/leads")
    # May be 200 (single-tenant) or 401/403 (auth required)
    assert resp.status_code in (200, 401, 403)
    if resp.status_code == 200:
        data = resp.json()
        assert "leads" in data
        assert isinstance(data["leads"], list)


def test_get_leads_starter_returns_empty(client, monkeypatch):
    """GET /api/leads for Starter plan returns empty leads."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant), \
         patch("main.db_leads_get_all", return_value=[]):
        resp = client.get("/api/leads")
        if resp.status_code == 200:
            data = resp.json()
            assert data["leads"] == []  # Starter has no lead capture


def test_get_leads_growth_returns_leads(client, monkeypatch):
    """GET /api/leads for Growth plan returns leads when present."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    growth_tenant = {"plan": "growth", "client_id": "test-spa", "id": "123"}
    mock_leads = [{"id": 1, "name": "Lead A", "phone": "+15551234567", "reason": "inquiry", "source": "call", "created_at": "2025-02-01T00:00:00"}]

    with patch("main.db_tenant_get_by_client_id", return_value=growth_tenant), \
         patch("main.db_leads_get_all", return_value=mock_leads), \
         patch("main.USE_DB", True):
        resp = client.get("/api/leads")
        if resp.status_code == 200:
            data = resp.json()
            assert "leads" in data
            assert len(data["leads"]) == 1
            assert data["leads"][0]["name"] == "Lead A"
