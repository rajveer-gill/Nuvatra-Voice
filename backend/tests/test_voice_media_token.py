"""Unit tests for media stream token, Twilio media JSON, and Deepgram transcript parsing."""

import json

from voice.deepgram_bridge import parse_deepgram_transcript_message
from voice.media_token import mint_media_stream_token, verify_media_stream_token
from voice.stt_config import deepgram_env_block_reason, voice_stt_provider
from voice.twilio_media import parse_twilio_media_message, twilio_media_payload_bytes, twilio_start_meta


def test_media_stream_token_roundtrip(monkeypatch):
    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "unit-test-secret")
    tok = mint_media_stream_token("CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert tok
    assert verify_media_stream_token(tok, "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert not verify_media_stream_token(tok, "CAbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")


def test_twilio_start_custom_parameters():
    raw = json.dumps(
        {
            "event": "start",
            "start": {
                "callSid": "CA111",
                "streamSid": "MZ222",
                "customParameters": {"token": "abc"},
            },
        }
    )
    ev = parse_twilio_media_message(raw)
    assert ev
    cs, ss, cp = twilio_start_meta(ev)
    assert cs == "CA111"
    assert ss == "MZ222"
    assert cp.get("token") == "abc"


def test_twilio_media_payload():
    import base64

    payload = base64.b64encode(b"\xff\x00").decode("ascii")
    raw = json.dumps({"event": "media", "media": {"payload": payload}})
    ev = parse_twilio_media_message(raw)
    b = twilio_media_payload_bytes(ev or {})
    assert b == b"\xff\x00"


def test_deepgram_transcript_message():
    msg = json.dumps(
        {
            "channel": {"alternatives": [{"transcript": "hello there", "confidence": 0.92}]},
            "is_final": True,
        }
    )
    out = parse_deepgram_transcript_message(msg)
    assert out == ("hello there", True, 0.92)


def test_deepgram_env_block_reason(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_STT_PROVIDER", "deepgram")
    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "x")
    assert deepgram_env_block_reason() == "missing_DEEPGRAM_API_KEY"

    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-key")
    monkeypatch.delenv("MEDIA_STREAM_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert deepgram_env_block_reason() == "missing_MEDIA_STREAM_SIGNING_SECRET_and_TWILIO_AUTH_TOKEN"

    monkeypatch.setenv("MEDIA_STREAM_SIGNING_SECRET", "sec")
    assert deepgram_env_block_reason() is None

    monkeypatch.setenv("VOICE_STT_PROVIDER", "twilio")
    assert deepgram_env_block_reason() is None
    assert voice_stt_provider() == "twilio"
