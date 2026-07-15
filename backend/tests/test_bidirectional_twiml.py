"""Bidirectional <Connect><Stream> TwiML builder for Option C."""
import pytest

from voice import twiml_stt


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    # Token minting needs a configured secret; stub it so we test TwiML shape, not crypto.
    monkeypatch.setattr(twiml_stt, "mint_media_stream_token", lambda sid, stream_generation: "tok123")


def test_builds_connect_stream_pointing_at_media_stream():
    xml = twiml_stt.bidirectional_stream_twiml(
        call_sid="CA" + "0" * 32, base_url="https://voice.example.test", stream_generation=1
    )
    assert xml is not None
    assert "<Connect>" in xml
    assert "wss://voice.example.test/api/phone/media-stream" in xml
    assert 'value="tok123"' in xml  # signed token parameter is included
    # No <Play>/<Gather> — the persistent stream handler owns greeting + listening.
    assert "<Play>" not in xml and "<Gather" not in xml


def test_includes_recording_start_when_callback_given():
    xml = twiml_stt.bidirectional_stream_twiml(
        call_sid="CA" + "1" * 32,
        base_url="https://voice.example.test",
        stream_generation=2,
        record_callback_url="https://voice.example.test/api/phone/recording-complete",
    )
    assert xml is not None
    assert "<Start>" in xml and "Record" in xml
    # Recording Start must come before the blocking <Connect>.
    assert xml.index("<Start>") < xml.index("<Connect>")


def test_returns_none_on_invalid_generation():
    xml = twiml_stt.bidirectional_stream_twiml(
        call_sid="CA" + "2" * 32, base_url="https://voice.example.test", stream_generation=0
    )
    assert xml is None  # caller falls back to the <Play> path


def test_returns_none_when_token_cannot_mint(monkeypatch):
    monkeypatch.setattr(twiml_stt, "mint_media_stream_token", lambda sid, stream_generation: "")
    xml = twiml_stt.bidirectional_stream_twiml(
        call_sid="CA" + "3" * 32, base_url="https://voice.example.test", stream_generation=1
    )
    assert xml is None
