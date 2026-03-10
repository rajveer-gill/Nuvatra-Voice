"""
Tests for POST /api/text-to-speech: voice preview and TTS pipeline.
Ensures the endpoint accepts valid payloads, uses voice_preview/add_sentence_pauses, and returns audio.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app, require_tenant


# Minimal MP3 frame bytes so response looks like audio
FAKE_MP3_BYTES = b"\xff\xfb\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00"


def _active_tenant():
    """Tenant with active subscription so require_active_subscription passes."""
    return {
        "id": "test-tenant-id",
        "client_id": "test-client",
        "plan": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": "2099-12-31T23:59:59Z",
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    return TestClient(app)


def test_text_to_speech_requires_auth(client, monkeypatch):
    """Without tenant/auth (multi-tenant mode), TTS returns 401 or 403."""
    monkeypatch.setenv("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")
    resp = client.post(
        "/api/text-to-speech",
        json={"text": "Hello", "voice": "fable"},
    )
    assert resp.status_code in (401, 403)


def test_text_to_speech_accepts_valid_payload_returns_audio(client):
    """POST with valid text and voice returns 200 and audio/mpeg body."""
    app.dependency_overrides[require_tenant] = _active_tenant
    mock_speech = MagicMock()
    mock_speech.content = FAKE_MP3_BYTES
    with patch("main.client") as mock_client:
        mock_client.audio.speech.create.return_value = mock_speech
        try:
            resp = client.post(
                "/api/text-to-speech",
                json={"text": "Hi there! Thanks for calling.", "voice": "fable", "speed": 1.0},
            )
            assert resp.status_code == 200
            assert "audio/mpeg" in resp.headers.get("content-type", "")
            assert resp.content == FAKE_MP3_BYTES
            # Endpoint should call add_sentence_pauses on input
            call_kw = mock_client.audio.speech.create.call_args[1]
            assert "input" in call_kw
            assert "Hi there" in call_kw["input"]
            assert call_kw.get("voice") == "fable"
            assert call_kw.get("model") == "tts-1-hd"
        finally:
            app.dependency_overrides.pop(require_tenant, None)


def test_text_to_speech_all_voices_accepted(client):
    """Each canonical voice is accepted by the endpoint (mock returns success)."""
    from voice_preview import TTS_VOICES

    app.dependency_overrides[require_tenant] = _active_tenant
    mock_speech = MagicMock()
    mock_speech.content = FAKE_MP3_BYTES
    with patch("main.client") as mock_client:
        mock_client.audio.speech.create.return_value = mock_speech
        try:
            for voice in TTS_VOICES:
                resp = client.post(
                    "/api/text-to-speech",
                    json={"text": "Hello.", "voice": voice},
                )
                assert resp.status_code == 200, f"voice={voice}"
                assert "audio/mpeg" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.pop(require_tenant, None)


def test_text_to_speech_speed_clamped(client):
    """Speed is clamped to 0.25–4.0."""
    app.dependency_overrides[require_tenant] = _active_tenant
    mock_speech = MagicMock()
    mock_speech.content = FAKE_MP3_BYTES
    with patch("main.client") as mock_client:
        mock_client.audio.speech.create.return_value = mock_speech
        try:
            resp = client.post(
                "/api/text-to-speech",
                json={"text": "Hi", "voice": "fable", "speed": 10.0},
            )
            assert resp.status_code == 200
            call_kw = mock_client.audio.speech.create.call_args[1]
            assert call_kw.get("speed") == 4.0
        finally:
            app.dependency_overrides.pop(require_tenant, None)
