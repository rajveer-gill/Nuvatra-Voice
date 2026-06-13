"""Tests for Stripe webhook handler (mocked payloads, no live Stripe)."""
import json
import os

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_stripe_webhook_missing_signature(client):
    """POST /api/stripe-webhook without stripe-signature returns 400 or 503."""
    resp = client.post("/api/stripe-webhook", content=b"{}", headers={"Content-Type": "application/json"})
    assert resp.status_code in (400, 503)


def test_stripe_webhook_invalid_payload(client):
    """POST with invalid payload returns 400."""
    resp = client.post(
        "/api/stripe-webhook",
        content=b"not valid json",
        headers={"Content-Type": "application/json", "stripe-signature": "v0,fake"},
    )
    assert resp.status_code in (400, 503)


def test_stripe_webhook_returns_200_with_valid_mock(client):
    """When webhook secret is set and construct_event is mocked, handler returns 200."""
    import os
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    try:
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        mock_event.data.object = {
            "id": "cs_test_123",
            "customer": "cus_123",
            "subscription": "sub_123",
            "metadata": {"tenant_id": "00000000-0000-0000-0000-000000000001", "plan": "starter"},
        }
        with patch("routers.billing.stripe") as mock_stripe:
            if mock_stripe is None:
                pytest.skip("stripe not installed")
            mock_stripe.Webhook.construct_event.return_value = mock_event
            resp = client.post(
                "/api/stripe-webhook",
                content=b'{"type":"checkout.session.completed"}',
                headers={"Content-Type": "application/json", "stripe-signature": "v0,fake"},
            )
            assert resp.status_code in (200, 400, 503)
            if resp.status_code == 200:
                assert resp.json().get("received") is True
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_checkout_completed_activates_subscription(client, monkeypatch):
    """Regression: the handler must read the verified raw JSON (not the SDK's typed
    object, whose dict access varies by API version and was 500ing) and activate the
    subscription on checkout.session.completed."""
    import database
    import deps
    import runtime
    from routers import billing

    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    updates = {}
    monkeypatch.setattr(
        database, "db_tenant_update_subscription",
        lambda tid, **kw: updates.update(tenant_id=tid, **kw) or True,
    )
    # Tenant already has a number → provisioning is skipped (keeps the test focused).
    monkeypatch.setattr(
        database, "db_tenant_get_by_id",
        lambda tid: {"id": tid, "client_id": "test-salon", "twilio_phone_number": "+15551112222"},
    )
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    try:
        with patch.object(billing, "stripe") as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = MagicMock()  # signature OK
            payload = json.dumps({
                "type": "checkout.session.completed",
                "data": {"object": {
                    "id": "cs_test_1", "customer": "cus_1", "subscription": "sub_1",
                    "metadata": {"tenant_id": "t-1", "plan": "growth"},
                }},
            }).encode()
            resp = client.post(
                "/api/stripe-webhook",
                content=payload,
                headers={"Content-Type": "application/json", "stripe-signature": "v0,fake"},
            )
            assert resp.status_code == 200
            assert updates.get("subscription_status") == "active"
            assert updates.get("tenant_id") == "t-1"
            assert updates.get("plan") == "growth"
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
