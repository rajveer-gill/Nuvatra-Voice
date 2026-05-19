"""Contract: inbound TwiML uses Connect+Stream when Deepgram STT is active."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def deepgram_phone_client(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.test")
    monkeypatch.setenv("CALL_RECORDING_ENABLED", "false")
    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "unit-test-media-hmac")
    import main

    monkeypatch.setattr(main, "_voice_stt_use_deepgram", lambda: True)
    monkeypatch.setattr(main, "twilio_client", object(), raising=False)
    monkeypatch.setattr(main, "_validate_twilio_webhook", lambda _r, _d: True)
    return TestClient(main.app)


def test_incoming_twiml_deepgram_connect_stream(deepgram_phone_client):
    resp = deepgram_phone_client.post(
        "/api/phone/incoming",
        data={
            "CallSid": "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "From": "+15551110001",
            "To": "+15552220002",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<Connect>" in body
    assert "wss://voice.example.test/api/phone/media" in body
    assert "<Stream" in body
    assert "token" in body.lower()
    assert "got-it-audio" in body
    assert "/api/phone/respond" in body
