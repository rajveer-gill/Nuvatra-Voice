"""Contract: respond_with_audio uses Connect+Stream for Latin follow-up turns when Deepgram STT is active."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def deepgram_respond_client(monkeypatch):
    from voice.call_session_store import MemoryCallSessionStore, reset_call_session_store_for_tests

    reset_call_session_store_for_tests(MemoryCallSessionStore())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.test")
    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "unit-test-media-hmac")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    import main

    monkeypatch.setattr(main, "_voice_stt_use_deepgram", lambda: True)
    monkeypatch.setattr("runtime.twilio_client", object(), raising=False)
    monkeypatch.setattr(main, "_validate_twilio_webhook", lambda _r, _d: True)
    return TestClient(main.app)


def test_respond_ready_twiml_uses_deepgram_streams_not_gather(deepgram_respond_client, monkeypatch):
    import main

    call_sid = "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    main.active_calls[call_sid] = {
        "client_id": "default",
        "conversation_history": [],
        "detected_language": "English",
        "twilio_public_base_url": "https://voice.example.test",
        "media_stream_gen": 0,
    }
    main.response_status[call_sid] = {
        "status": "ready",
        "audio_url": "https://voice.example.test/api/phone/tts-audio?text=hi",
    }
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    monkeypatch.setattr(main, "get_business_info", lambda: {"forwarding_phone": ""})

    resp = deepgram_respond_client.post(
        "/api/phone/respond",
        data={"CallSid": call_sid},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<Connect>" in body
    assert "wss://voice.example.test/api/phone/media" in body
    assert body.count("<Connect>") >= 2
    assert "Still there" not in body or "tts-audio" in body
    assert "<Gather" not in body


def test_respond_ready_twiml_handles_null_detected_language(deepgram_respond_client, monkeypatch):
    """Redis sessions may still have detected_language: null from older creates."""
    import main

    call_sid = "CAbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    main.active_calls[call_sid] = {
        "client_id": "default",
        "conversation_history": [],
        "detected_language": None,
        "twilio_public_base_url": "https://voice.example.test",
        "media_stream_gen": 2,
    }
    main.response_status[call_sid] = {
        "status": "ready",
        "audio_url": "https://voice.example.test/api/phone/tts-audio?text=hi",
    }
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    monkeypatch.setattr(main, "get_business_info", lambda: {"forwarding_phone": ""})

    resp = deepgram_respond_client.post(
        "/api/phone/respond",
        data={"CallSid": call_sid},
    )
    assert resp.status_code == 200
    assert "<Connect>" in resp.text
    assert "<Hangup" not in resp.text
