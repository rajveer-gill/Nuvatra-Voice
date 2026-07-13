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
    with patch("runtime.client") as mock_client:
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
            # Uses the configured (steerable) TTS model, and forwards delivery
            # instructions when that model is a gpt-4o TTS model.
            import config_service

            assert call_kw.get("model") == config_service.get_tts_model()
            if config_service.get_tts_model().startswith("gpt-"):
                assert call_kw.get("instructions")
        finally:
            app.dependency_overrides.pop(require_tenant, None)


def test_text_to_speech_all_voices_accepted(client):
    """Each canonical voice is accepted by the endpoint (mock returns success)."""
    from voice_preview import TTS_VOICES

    app.dependency_overrides[require_tenant] = _active_tenant
    mock_speech = MagicMock()
    mock_speech.content = FAKE_MP3_BYTES
    with patch("runtime.client") as mock_client:
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


def test_synthesize_clip_forwards_instructions_only_for_gpt_model():
    """gpt-4o TTS models receive delivery `instructions`; tts-1/tts-1-hd must not (they reject it)."""
    import voice_service

    mock_speech = MagicMock()
    mock_speech.content = FAKE_MP3_BYTES
    with patch("runtime.client") as mock_client:
        mock_client.audio.speech.create.return_value = mock_speech

        voice_service._synthesize_tts_clip(
            "Hello.", voice="fable", speed=1.0, model="gpt-4o-mini-tts", instructions="Be warm."
        )
        gpt_kw = mock_client.audio.speech.create.call_args[1]
        assert gpt_kw["model"] == "gpt-4o-mini-tts"
        assert gpt_kw.get("instructions") == "Be warm."

        voice_service._synthesize_tts_clip(
            "Hello.", voice="fable", speed=1.0, model="tts-1", instructions="Be warm."
        )
        legacy_kw = mock_client.audio.speech.create.call_args[1]
        assert legacy_kw["model"] == "tts-1"
        assert "instructions" not in legacy_kw


def test_tts_variant_suffix_changes_with_model_env(monkeypatch):
    """Switching VOICE_TTS_MODEL changes the clip cache-key suffix so stale mp3s are bypassed."""
    import voice_service

    monkeypatch.setenv("VOICE_TTS_MODEL", "gpt-4o-mini-tts")
    gpt_suffix = voice_service._tts_variant_suffix()
    monkeypatch.setenv("VOICE_TTS_MODEL", "tts-1-hd")
    legacy_suffix = voice_service._tts_variant_suffix()

    assert gpt_suffix != legacy_suffix
    assert gpt_suffix[0] == "gpt-4o-mini-tts"
    assert legacy_suffix[0] == "tts-1-hd"
    # instructions fingerprint is present for the steerable model, empty for tts-1-hd
    assert gpt_suffix[1] != ""
    assert legacy_suffix[1] == ""


def test_text_to_speech_speed_clamped(client):
    """Speed is clamped to 0.25–4.0."""
    app.dependency_overrides[require_tenant] = _active_tenant
    mock_speech = MagicMock()
    mock_speech.content = FAKE_MP3_BYTES
    with patch("runtime.client") as mock_client:
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
