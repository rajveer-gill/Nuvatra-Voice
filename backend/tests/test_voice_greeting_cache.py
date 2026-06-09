"""Greeting TTS cache: ensure before TwiML, no duplicate synthesis on hit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import main
import voice_service


@pytest.fixture
def voice_cache_env(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_service, "PROJECT_ROOT", tmp_path)
    cid = "cache-tenant"
    cfg_path = tmp_path / "clients" / cid / "config.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        json.dumps(
            {
                "client_id": cid,
                "business_name": "Cache Spa",
                "voice": "nova",
                "greeting": "",
                "speed": 1.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("runtime.USE_DB", False)
    monkeypatch.setattr(voice_service, "_call_recording_enabled_for_tenant", lambda _t: True)
    monkeypatch.setattr(voice_service, "_tenant_for_call_recording", lambda: None)
    return cid


def test_ensure_greeting_audio_cached_skips_resynthesis(voice_cache_env, monkeypatch):
    cid = voice_cache_env
    calls = {"n": 0}

    def fake_synthesize(text, *, voice, speed):
        calls["n"] += 1
        return b"mp3-bytes"

    monkeypatch.setattr(voice_service, "_synthesize_tts_clip", fake_synthesize)
    main.set_request_client_id(cid)

    assert main._ensure_greeting_audio_cached(cid) is True
    assert calls["n"] == 1
    assert main._ensure_greeting_audio_cached(cid) is True
    assert calls["n"] == 1
