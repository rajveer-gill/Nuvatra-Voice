"""Webhook subscription enforcement (voice + SMS)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from subscription_access import get_tenant_subscription_state, tenant_can_use_app
from webhook_responses import (
    SMS_SUBSCRIPTION_LAPSED_MESSAGE,
    check_webhook_tenant_access,
    subscription_denied_voice_twiml,
)


def _future_iso():
    return (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()


def _past_iso():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


@pytest.mark.parametrize(
    "tenant,expected",
    [
        ({"plan": "starter", "subscription_status": "active"}, True),
        ("trialing_active", True),
        ("trialing_expired", False),
        ({"plan": "starter", "subscription_status": "canceled"}, False),
        ("no_tenant_no_db", True),
        ("no_tenant_db", False),
    ],
)
def test_tenant_can_use_app_states(tenant, expected, monkeypatch):
    if tenant == "trialing_active":
        tenant = {"plan": "free", "subscription_status": "trialing", "trial_ends_at": _future_iso()}
    elif tenant == "trialing_expired":
        tenant = {"plan": "free", "subscription_status": "trialing", "trial_ends_at": _past_iso()}
    elif tenant == "no_tenant_no_db":
        import main

        monkeypatch.setattr("runtime.USE_DB", False)
        tenant = None
    elif tenant == "no_tenant_db":
        import main

        monkeypatch.setattr("runtime.USE_DB", True)
        tenant = None
    assert tenant_can_use_app(tenant) is expected


def test_missing_tenant_denied_when_db_mode(monkeypatch):
    import main

    monkeypatch.setattr("runtime.USE_DB", True)
    from subscription_access import webhook_access_denial_reason

    assert webhook_access_denial_reason(None) == "tenant_not_found"
    assert check_webhook_tenant_access(None, channel="voice") is False


def test_subscription_denied_voice_twiml_valid():
    body = subscription_denied_voice_twiml()
    assert "<Response>" in body
    assert "<Say" in body
    assert "<Hangup" in body
    assert "unavailable" in body.lower()


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    import main

    # Phone handler (still in main) resolves _validate_twilio_webhook via main's re-export;
    # the SMS handler (routers/sms) resolves it via deps. Patch both so the bypass reaches
    # whichever handler the test exercises.
    monkeypatch.setattr(main, "_validate_twilio_webhook", lambda _r, _d: True)
    monkeypatch.setattr("deps._validate_twilio_webhook", lambda _r, _d: True)
    monkeypatch.setattr(main, "TWILIO_AVAILABLE", True)
    if main.VoiceResponse is None:
        pytest.skip("Twilio not installed")
    return TestClient(main.app)


def test_incoming_call_expired_subscription_returns_twiml(webhook_client, monkeypatch):
    import main

    past = _past_iso()
    tenant = {
        "client_id": "expired-co",
        "name": "Expired",
        "twilio_phone_number": "+15552220002",
        "plan": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": past,
        "created_at": past,
    }
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(main, "db_tenant_get_by_phone", lambda _p: tenant)
    monkeypatch.setattr(main, "db_tenant_get_by_client_id", lambda _c: tenant)
    resp = webhook_client.post(
        "/api/phone/incoming",
        data={
            "CallSid": "CAbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "From": "+15551110001",
            "To": "+15552220002",
        },
    )
    assert resp.status_code == 200
    assert "<Hangup" in resp.text
    assert "unavailable" in resp.text.lower()


def test_sms_incoming_expired_sends_polite_message(webhook_client, monkeypatch):
    import main

    sent = []

    def capture_send(to, body, **kwargs):
        sent.append((to, body))
        return True

    past = _past_iso()
    tenant = {
        "client_id": "expired-sms",
        "name": "Expired SMS",
        "twilio_phone_number": "+15552220002",
        "plan": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": past,
        "created_at": past,
    }
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr("database.db_tenant_get_by_phone", lambda _p: tenant)
    monkeypatch.setattr("sms_service.send_sms", capture_send)
    resp = webhook_client.post(
        "/api/sms/incoming",
        data={
            "From": "+15551110001",
            "To": "+15552220002",
            "Body": "Hello",
        },
    )
    assert resp.status_code == 200
    assert sent
    assert SMS_SUBSCRIPTION_LAPSED_MESSAGE in sent[0][1]
