"""Tests for subscription state and enforcement."""
import pytest
from fastapi.testclient import TestClient
from main import app, get_tenant_subscription_state


@pytest.fixture
def client():
    return TestClient(app)


def test_get_subscription_endpoint(client):
    """GET /api/subscription returns 200 or 401/403; when 200 includes can_use_app, limits, usage."""
    resp = client.get("/api/subscription")
    assert resp.status_code in (200, 401, 403)
    if resp.status_code == 200:
        data = resp.json()
        assert "can_use_app" in data
        assert "subscription_status" in data or data.get("subscription_status") is None
        assert "plan" in data
        assert "limits" in data
        assert "usage" in data


def test_subscription_includes_limits(client):
    """GET /api/subscription returns limits with plan tier keys."""
    resp = client.get("/api/subscription")
    if resp.status_code == 200:
        limits = resp.json().get("limits", {})
        assert "plan" in limits
        assert "minutes_cap" in limits
        assert "staff_max" in limits
        assert "call_log_days" in limits
        assert "has_reminders" in limits
        assert "has_lead_capture" in limits
        assert "sms_automations_max" in limits
        assert "has_export" in limits


def test_subscription_includes_usage(client):
    """GET /api/subscription returns usage with voice_minutes, sms_count, month."""
    resp = client.get("/api/subscription")
    if resp.status_code == 200:
        usage = resp.json().get("usage", {})
        assert "voice_minutes" in usage
        assert "sms_count" in usage
        assert "month" in usage


def test_subscription_state_single_tenant():
    """When tenant is None (single-tenant), can_use_app is True."""
    state = get_tenant_subscription_state(None)
    assert state["can_use_app"] is True
    assert state.get("plan") is not None


def test_subscription_state_trialing():
    """When subscription_status is trialing and trial_ends_at in future, can_use_app True."""
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    tenant = {
        "trial_ends_at": future,
        "subscription_status": "trialing",
        "plan": "free",
        "billing_exempt_until": None,
    }
    state = get_tenant_subscription_state(tenant)
    assert state["can_use_app"] is True


def test_subscription_state_trial_ended_no_subscription():
    """When trial ended and no active subscription, can_use_app False."""
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    tenant = {
        "trial_ends_at": past,
        "subscription_status": "trialing",
        "plan": "free",
        "billing_exempt_until": None,
    }
    with patch("main.USE_DB", True):
        state = get_tenant_subscription_state(tenant)
    assert state["can_use_app"] is False


def test_subscription_state_active():
    """When subscription_status is active, can_use_app True."""
    tenant = {
        "trial_ends_at": None,
        "subscription_status": "active",
        "plan": "starter",
        "billing_exempt_until": None,
    }
    state = get_tenant_subscription_state(tenant)
    assert state["can_use_app"] is True


def test_subscription_state_billing_exempt():
    """When billing_exempt_until is in future, can_use_app True."""
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    tenant = {
        "trial_ends_at": None,
        "subscription_status": "canceled",
        "plan": "free",
        "billing_exempt_until": future,
    }
    state = get_tenant_subscription_state(tenant)
    assert state["can_use_app"] is True


def test_protected_endpoint_auth_or_subscription(client):
    """Dashboard APIs return 200, 401, or 403 (auth/subscription required in multi-tenant)."""
    resp = client.get("/api/business-info")
    assert resp.status_code in (200, 401, 403)
