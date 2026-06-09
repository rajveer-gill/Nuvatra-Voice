"""Regression: inbound TwiML must nest greeting <Play> inside <Gather> for reliable audio."""

import os
import deps
import config_service

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def phone_client(monkeypatch):
    """Skip Twilio signature validation in unit tests (CI may load TWILIO_AUTH_TOKEN from .env)."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CALL_RECORDING_ENABLED", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.test")
    import main

    monkeypatch.setattr(deps, "_validate_twilio_webhook", lambda _r, _d: True)
    monkeypatch.setattr("runtime.USE_DB", False)
    monkeypatch.setattr(config_service, "voice_receptionist_ready", lambda info=None: True)
    return TestClient(main.app)


def test_incoming_twiml_nests_greeting_play_inside_gather(phone_client):
    resp = phone_client.post(
        "/api/phone/incoming",
        data={
            "CallSid": "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "From": "+15551110001",
            "To": "+15552220002",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<Gather" in body and "<Play" in body
    i_g = body.index("<Gather")
    i_p = body.index("greeting-audio")
    i_gc = body.index("</Gather>")
    assert i_g < i_p < i_gc, "greeting Play should be nested inside Gather, not a prior sibling"
