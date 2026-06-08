"""Contract: inbound TwiML uses Connect+Stream when Deepgram STT is active."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def deepgram_phone_client(monkeypatch):
    from voice.call_session_store import MemoryCallSessionStore, reset_call_session_store_for_tests

    reset_call_session_store_for_tests(MemoryCallSessionStore())
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.test")
    monkeypatch.setenv("CALL_RECORDING_ENABLED", "false")
    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "unit-test-media-hmac")
    import main

    monkeypatch.setattr(main, "_voice_stt_use_deepgram", lambda: True)
    monkeypatch.setattr("runtime.twilio_client", object(), raising=False)
    monkeypatch.setattr(main, "_validate_twilio_webhook", lambda _r, _d: True)
    monkeypatch.setattr("runtime.USE_DB", False)
    monkeypatch.setattr(main, "voice_receptionist_ready", lambda info=None: True)
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
    assert "greeting-audio" in body
    assert "Still there" in body or "Still%20there" in body
    assert "/api/phone/no-speech" in body
    # got-it + /respond only after caller speech (REST update), not in initial TwiML
    assert "got-it-audio" not in body
    assert "/api/phone/respond" not in body


def test_incoming_twiml_persists_media_stream_gen(deepgram_phone_client):
    """Redis path: stream generation must be in store before Twilio opens media WS."""
    import main

    sid = "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    resp = deepgram_phone_client.post(
        "/api/phone/incoming",
        data={
            "CallSid": sid,
            "From": "+15551110001",
            "To": "+15552220002",
        },
    )
    assert resp.status_code == 200
    row = main.call_store.get(sid) or {}
    assert int(row.get("media_stream_gen") or 0) >= 2
    assert (row.get("twilio_public_base_url") or "").startswith("https://")
