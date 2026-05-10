"""Tests for salon/chair booking helpers: parse_booking, normalization, preview decline, polish."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import (
    app,
    polish_owner_decline_sms,
    _normalize_service_entries,
    _normalize_special_entries,
    _normalize_rule_entries,
    require_tenant,
)


def _active_tenant():
    return {
        "id": "test-tenant-id",
        "client_id": "test-client",
        "plan": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": "2099-12-31T23:59:59Z",
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    return TestClient(app)


def test_normalize_service_entries_caps_count():
    rows = [{"id": str(i), "name": f"S{i}", "price": 10, "duration_minutes": 30} for i in range(150)]
    out = _normalize_service_entries(rows)
    assert len(out) == 100


def test_normalize_specials_caps_count():
    rows = [{"id": str(i), "title": f"T{i}", "description": "", "valid_until": ""} for i in range(120)]
    out = _normalize_special_entries(rows)
    assert len(out) == 80


def test_normalize_rules_caps_count():
    rows = [{"id": str(i), "rule_text": f"rule{i}"} for i in range(150)]
    out = _normalize_rule_entries(rows)
    assert len(out) == 100


def test_polish_owner_decline_sms_fallback_on_openai_error():
    with patch("main.client") as mock_client:
        mock_client.chat.completions.create.side_effect = RuntimeError("no network")
        out = polish_owner_decline_sms(
            "We're booked at 2pm",
            "Test Salon",
            {"date": "2025-06-01", "time": "14:00"},
        )
    assert "booked" in out.lower() or "2" in out


def test_preview_decline_sms_requires_reason(client):
    app.dependency_overrides[require_tenant] = _active_tenant
    try:
        resp = client.post("/api/appointments/preview-decline-sms", json={})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(require_tenant, None)


def test_preview_decline_sms_returns_polished_message(client):
    app.dependency_overrides[require_tenant] = _active_tenant
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Hi — we can't do 2pm. Want 4pm?"))]
    try:
        with patch("main.client") as mock_client:
            mock_client.chat.completions.create.return_value = mock_resp
            resp = client.post(
                "/api/appointments/preview-decline-sms",
                json={"reason": "Stylist booked at 2"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "polished_message" in data
        assert len(data["polished_message"]) > 0
    finally:
        app.dependency_overrides.pop(require_tenant, None)
