"""Tests for pre-launch hardening: account pause, split metering, Twilio release,
booking past-date rejection, and overage pricing."""
from datetime import timedelta
from unittest.mock import patch

import pytest

import business_hours
from booking_fields import booking_context_from_business, normalize_and_validate_booking
from plans import get_plan_limits
from subscription_access import get_tenant_subscription_state, webhook_access_denial_reason


# --- §1: account_paused flows through the access gate -----------------------

def _active_tenant(**over):
    t = {
        "trial_ends_at": None,
        "subscription_status": "active",
        "plan": "growth",
        "billing_exempt_until": None,
        "account_paused": False,
    }
    t.update(over)
    return t


def test_paused_active_tenant_cannot_use_app():
    state = get_tenant_subscription_state(_active_tenant(account_paused=True))
    assert state["can_use_app"] is False
    assert state["account_paused"] is True


def test_unpaused_active_tenant_can_use_app():
    state = get_tenant_subscription_state(_active_tenant(account_paused=False))
    assert state["can_use_app"] is True


def test_paused_overrides_active_trial():
    future = (business_hours.business_local_now({}) + timedelta(days=5)).isoformat()
    tenant = _active_tenant(subscription_status="trialing", trial_ends_at=future, account_paused=True)
    with patch("runtime.USE_DB", True):
        state = get_tenant_subscription_state(tenant)
    assert state["can_use_app"] is False


def test_webhook_denial_reason_account_paused():
    assert webhook_access_denial_reason(_active_tenant(account_paused=True)) == "account_paused"
    assert webhook_access_denial_reason(_active_tenant(account_paused=False)) is None


# --- §2a: sms_cap is exposed and independent of minutes_cap -----------------

def test_plan_limits_expose_sms_cap():
    for plan, expected in [("starter", 100), ("growth", 300), ("pro", 1000)]:
        limits = get_plan_limits({"plan": plan, "subscription_status": "active"})
        assert limits["sms_cap"] == expected
        assert "minutes_cap" in limits and limits["minutes_cap"] != limits["sms_cap"]


# --- §2: overage pricing ----------------------------------------------------

def test_overage_prices_resolve():
    from billing_config import get_overage_price_per_minute, get_overage_price_per_sms

    assert get_overage_price_per_minute() >= 0
    assert get_overage_price_per_sms() >= 0


# --- §6: booking past-date / past-time rejection ----------------------------

def _ctx():
    return booking_context_from_business(
        {"staff": [{"id": "j1", "name": "Jake"}], "services": [{"name": "Cut"}]}
    )


def test_booking_rejects_past_date():
    past = (business_hours.business_local_now({}) - timedelta(days=2)).date().isoformat()
    booking = {"name": "Raj", "date": past, "time": "15:00", "reason": "Cut", "staff": "Jake"}
    prepared, _repairs, reject = normalize_and_validate_booking(booking, _ctx())
    assert prepared is None
    assert reject == "past_date"


def test_booking_accepts_future_date():
    future = (business_hours.business_local_now({}) + timedelta(days=3)).date().isoformat()
    booking = {"name": "Raj", "date": future, "time": "15:00", "reason": "Cut", "staff": "Jake"}
    prepared, _repairs, reject = normalize_and_validate_booking(booking, _ctx())
    assert reject is None
    assert prepared is not None


def test_booking_legacy_context_without_now_skips_past_check():
    """A context built without a reference 'now' keeps prior behavior (no past-date check)."""
    from booking_fields import BookingFieldContext

    ctx = BookingFieldContext(staff_names=frozenset(), service_names=frozenset())
    booking = {"name": "Raj", "date": "2000-01-01", "time": "15:00", "reason": "", "staff": ""}
    prepared, _repairs, reject = normalize_and_validate_booking(booking, ctx)
    assert reject is None  # no today in context → not rejected as past


# --- §4: twilio_provision.release_number ------------------------------------

class _FakeNumberCtx:
    def __init__(self, recorder):
        self._rec = recorder

    def delete(self):
        self._rec.append("number_deleted")


class _FakeIncomingNumbers:
    def __init__(self, recorder, existing_sid="PNexisting"):
        self._rec = recorder
        self._existing_sid = existing_sid

    def list(self, phone_number=None, limit=None):
        if self._existing_sid:
            return [type("N", (), {"sid": self._existing_sid, "phone_number": phone_number})()]
        return []

    def __call__(self, sid):
        self._rec.append(("number_ctx", sid))
        return _FakeNumberCtx(self._rec)


class _FakeClient:
    def __init__(self, recorder, existing_sid="PNexisting"):
        self.incoming_phone_numbers = _FakeIncomingNumbers(recorder, existing_sid)


def test_release_number_deletes_when_sid_known(monkeypatch):
    import twilio_provision

    rec = []
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda *a, **k: _FakeClient(rec))
    monkeypatch.setattr(twilio_provision, "a2p_messaging_service_sid", lambda: "")
    out = twilio_provision.release_number(
        account_sid="AC", auth_token="tok", phone_e164="+15551230000", number_sid="PN123"
    )
    assert out["released"] is True
    assert ("number_ctx", "PN123") in rec
    assert "number_deleted" in rec


def test_release_number_looks_up_sid_when_absent(monkeypatch):
    import twilio_provision

    rec = []
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda *a, **k: _FakeClient(rec, "PNlooked"))
    monkeypatch.setattr(twilio_provision, "a2p_messaging_service_sid", lambda: "")
    out = twilio_provision.release_number(
        account_sid="AC", auth_token="tok", phone_e164="+15551230000"
    )
    assert out["released"] is True
    assert out["number_sid"] == "PNlooked"


def test_release_number_idempotent_when_already_gone(monkeypatch):
    import twilio_provision

    rec = []
    # No existing number in the account → already released.
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda *a, **k: _FakeClient(rec, existing_sid=None))
    monkeypatch.setattr(twilio_provision, "a2p_messaging_service_sid", lambda: "")
    out = twilio_provision.release_number(
        account_sid="AC", auth_token="tok", phone_e164="+15551230000"
    )
    assert out["released"] is True


def test_release_number_missing_creds_no_raise():
    import twilio_provision

    out = twilio_provision.release_number(account_sid="", auth_token="", phone_e164="+15551230000")
    assert out["released"] is False
    assert "twilio_credentials_required" in out["errors"]


# --- §5: per-call runaway protection ----------------------------------------

def test_tts_endpoints_are_rate_limited():
    import main

    assert "/api/phone/tts-audio" in main._RATE_LIMITED_PATHS
    assert "/api/phone/tts-audio-hd" in main._RATE_LIMITED_PATHS


def test_tts_audio_truncates_long_text(monkeypatch):
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from main import app
    from routers import phone as phone_router

    mock_speech = MagicMock()
    mock_speech.content = b"ID3fake-mp3"
    with patch("runtime.client") as mock_client:
        mock_client.audio.speech.create.return_value = mock_speech
        client = TestClient(app)
        resp = client.get("/api/phone/tts-audio", params={"text": "a" * 5000, "voice": "fable"})
        assert resp.status_code == 200
        call_kw = mock_client.audio.speech.create.call_args[1]
        # Input is clamped to the cap (plus any pause formatting), never the full 5000.
        assert len(call_kw["input"]) <= phone_router.TTS_MAX_INPUT_CHARS + 50


def test_call_turn_cap_wraps_up_and_hangs_up(monkeypatch):
    """Exceeding the per-call turn cap returns terminal wrap-up TwiML instead of looping."""
    import asyncio
    import time as _time

    from voice.call_session_store import MemoryCallSessionStore, reset_call_session_store_for_tests
    import main
    from voice import utterance as utt

    reset_call_session_store_for_tests(MemoryCallSessionStore())
    monkeypatch.setattr(main, "get_business_info", lambda: {"forwarding_phone": ""})

    call_sid = "CAabcdef0123456789abcdef0123456789"
    main.active_calls[call_sid] = {
        "client_id": "test",
        "conversation_history": [],
        "detected_language": "English",
        "started_at_epoch": _time.time(),
        "turn_count": utt.MAX_USER_TURNS,  # next utterance pushes it over
    }

    result = asyncio.run(
        utt.apply_caller_utterance(call_sid, "I'd like to book again", 0.9, "https://voice.example.test")
    )
    assert result.mode == "replace_call_twiml"
    assert "Hangup" in result.replacement_twiml  # no forwarding phone → graceful hangup
