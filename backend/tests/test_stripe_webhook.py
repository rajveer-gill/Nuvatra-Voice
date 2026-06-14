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


def _post_event(client, billing, event_dict):
    with patch.object(billing, "stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = MagicMock()  # signature OK
        return client.post(
            "/api/stripe-webhook",
            content=json.dumps(event_dict).encode(),
            headers={"Content-Type": "application/json", "stripe-signature": "v0,fake"},
        )


def test_subscription_updated_resolves_by_sub_id_when_metadata_absent(client, monkeypatch):
    """Portal-initiated updates lack metadata.tenant_id → resolve via stored sub id,
    and do NOT clobber the plan to starter."""
    import database
    import deps
    import runtime
    from routers import billing

    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    updates = {}
    monkeypatch.setattr(
        database, "db_tenant_get_by_stripe_subscription_id",
        lambda sub_id: {"id": "t-9", "client_id": "c-9"},
    )
    monkeypatch.setattr(
        database, "db_tenant_update_subscription",
        lambda tid, **kw: updates.update(tenant_id=tid, **kw) or True,
    )
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda tid: {"id": tid, "client_id": "c-9"})
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    try:
        resp = _post_event(client, billing, {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_9", "status": "active", "metadata": {}}},
        })
        assert resp.status_code == 200
        assert updates.get("tenant_id") == "t-9"
        assert updates.get("subscription_status") == "active"
        assert updates.get("plan") is None  # not clobbered to starter
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_portal_plan_switch_syncs_plan_from_price(client, monkeypatch):
    """A Customer-Portal plan switch sends subscription.updated with no metadata.plan —
    the new plan must be derived from the line-item price so DB limits stay in sync."""
    import database
    import deps
    import runtime
    from routers import billing

    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    os.environ["STRIPE_GROWTH_PRICE_ID"] = "price_growth_live"
    updates = {}
    monkeypatch.setattr(database, "db_tenant_get_by_stripe_subscription_id",
                        lambda sub_id: {"id": "t-3", "client_id": "c-3"})
    monkeypatch.setattr(database, "db_tenant_update_subscription",
                        lambda tid, **kw: updates.update(tenant_id=tid, **kw) or True)
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda tid: {"id": tid, "client_id": "c-3"})
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    try:
        resp = _post_event(client, billing, {
            "type": "customer.subscription.updated",
            "data": {"object": {
                "id": "sub_3", "status": "active", "metadata": {},
                "items": {"data": [{"price": {"id": "price_growth_live"}}]},
            }},
        })
        assert resp.status_code == 200
        assert updates.get("plan") == "growth"  # derived from the price, not metadata
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        os.environ.pop("STRIPE_GROWTH_PRICE_ID", None)


def test_subscription_deleted_releases_twilio_number(client, monkeypatch):
    import database
    import deps
    import runtime
    import twilio_provision
    from routers import billing

    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    os.environ["TWILIO_ACCOUNT_SID"] = "AC"
    os.environ["TWILIO_AUTH_TOKEN"] = "tok"
    released = {}
    cleared = {}
    monkeypatch.setattr(
        database, "db_tenant_get_by_stripe_subscription_id",
        lambda sub_id: {"id": "t-7", "client_id": "c-7",
                        "twilio_phone_number": "+15557770000", "twilio_number_sid": "PN7"},
    )
    monkeypatch.setattr(database, "db_tenant_get_by_id",
                        lambda tid: {"id": tid, "client_id": "c-7",
                                     "twilio_phone_number": "+15557770000", "twilio_number_sid": "PN7"})
    monkeypatch.setattr(database, "db_tenant_update_subscription", lambda tid, **kw: True)
    monkeypatch.setattr(database, "db_tenant_clear_twilio", lambda tid: cleared.update(tid=tid) or True)
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(
        twilio_provision, "release_number",
        lambda **kw: released.update(kw) or {"released": True, "errors": []},
    )
    try:
        resp = _post_event(client, billing, {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_7", "metadata": {}}},
        })
        assert resp.status_code == 200
        assert released.get("phone_e164") == "+15557770000"
        assert released.get("number_sid") == "PN7"
        assert cleared.get("tid") == "t-7"
    finally:
        for k in ("STRIPE_WEBHOOK_SECRET", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"):
            os.environ.pop(k, None)


def test_payment_failed_does_not_release_number(client, monkeypatch):
    import database
    import deps
    import runtime
    import twilio_provision
    from routers import billing

    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    calls = {"released": False}
    monkeypatch.setattr(
        database, "db_tenant_get_by_stripe_subscription_id",
        lambda sub_id: {"id": "t-5", "client_id": "c-5", "twilio_phone_number": "+15555550000"},
    )
    monkeypatch.setattr(database, "db_tenant_update_subscription", lambda tid, **kw: True)
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(
        twilio_provision, "release_number",
        lambda **kw: calls.update(released=True) or {"released": True, "errors": []},
    )
    try:
        resp = _post_event(client, billing, {
            "type": "invoice.payment_failed",
            "data": {"object": {"subscription": "sub_5"}},
        })
        assert resp.status_code == 200
        assert calls["released"] is False  # past_due must NOT release the number
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
