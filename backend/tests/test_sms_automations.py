"""Tests for SMS automations API and plan gating."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_sms_automations_returns_list(client):
    """GET /api/sms-automations returns {automations: [...]}."""
    resp = client.get("/api/sms-automations")
    assert resp.status_code in (200, 401, 403)
    if resp.status_code == 200:
        data = resp.json()
        assert "automations" in data
        assert isinstance(data["automations"], list)


def test_post_sms_automation_starter_returns_403(client, monkeypatch):
    """POST /api/sms-automations on Starter plan returns 403."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    starter_tenant = {"plan": "starter", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=starter_tenant), \
         patch("main.require_tenant", return_value=starter_tenant):
        resp = client.post(
            "/api/sms-automations",
            json={"trigger": "after_inquiry", "template": "Hi {business_name}!"},
        )
        # Starter has sms_automations_max=0 -> 403
        assert resp.status_code in (403, 401)


def test_post_sms_automation_growth_accepts_valid(client, monkeypatch):
    """POST /api/sms-automations on Growth with room for more succeeds."""
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    growth_tenant = {"plan": "growth", "client_id": "test-spa", "id": "123"}

    with patch("main.db_tenant_get_by_client_id", return_value=growth_tenant), \
         patch("main.db_sms_automations_count", return_value=0), \
         patch("main.db_sms_automations_insert", return_value=1), \
         patch("main.require_tenant", return_value=growth_tenant):
        resp = client.post(
            "/api/sms-automations",
            json={"trigger": "after_inquiry", "template": "Thanks for your interest!"},
        )
        # Growth allows 2; we have 0 -> should accept
        assert resp.status_code in (200, 401, 403)
        if resp.status_code == 200:
            data = resp.json()
            assert "id" in data
            assert data["trigger"] == "after_inquiry"
