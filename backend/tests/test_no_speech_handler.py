"""No-speech webhook: race skips and post-AI reprompt behavior."""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def no_speech_client(monkeypatch):
    from voice.call_session_store import MemoryCallSessionStore, reset_call_session_store_for_tests

    reset_call_session_store_for_tests(MemoryCallSessionStore())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.test")
    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "unit-test-media-hmac")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    import main

    monkeypatch.setattr(main, "_validate_twilio_webhook", lambda _r, _d: True)
    monkeypatch.setattr(main, "_voice_stt_use_deepgram", lambda: True)
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    monkeypatch.setattr(main, "get_business_info", lambda: {"forwarding_phone": ""})
    return TestClient(main.app)


def test_no_speech_skips_to_respond_when_gpt_in_flight(no_speech_client):
    import main

    call_sid = "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    main.active_calls[call_sid] = {
        "client_id": "test",
        "conversation_history": [],
        "last_utterance_at": time.time(),
    }
    main.response_status[call_sid] = {"status": "pending"}

    resp = no_speech_client.post(
        "/api/phone/no-speech",
        data={"CallSid": call_sid},
    )
    assert resp.status_code == 200
    assert "/api/phone/respond" in resp.text


def test_no_speech_post_ai_reprompt_not_respond_poll(no_speech_client):
    """Recent speech must not redirect to /respond after AI reply TwiML cleared response_status."""
    import main

    call_sid = "CAbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    main.active_calls[call_sid] = {
        "client_id": "test",
        "conversation_history": [{"role": "user", "content": "book tomorrow"}],
        "last_utterance_at": time.time() - 10,
        "awaiting_caller_reply": True,
        "media_stream_gen": 4,
    }

    resp = no_speech_client.post(
        "/api/phone/no-speech",
        data={"CallSid": call_sid},
    )
    assert resp.status_code == 200
    assert "/api/phone/respond" not in resp.text
    assert "didn't quite catch that" in resp.text.lower() or "Connect" in resp.text
    assert main.active_calls[call_sid].get("awaiting_caller_reply") is False
