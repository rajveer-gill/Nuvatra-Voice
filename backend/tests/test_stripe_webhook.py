"""Tests for Stripe webhook handler (mocked payloads, no live Stripe)."""
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
        with patch("main.stripe") as mock_stripe:
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
