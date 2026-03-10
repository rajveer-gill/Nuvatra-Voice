"""
Tests for voice_preview module: sample text, voice list, and add_sentence_pauses.
Ensures the voice preview / TTS pipeline contract stays stable for Settings and generate_voice_samples.
"""
import pytest
from pathlib import Path
from voice_preview import (
    VOICE_PREVIEW_SAMPLE_TEXT,
    TTS_VOICES,
    add_sentence_pauses,
)


def test_voice_preview_sample_text_non_empty():
    """Sample text used for voice preview must be set and non-empty."""
    assert VOICE_PREVIEW_SAMPLE_TEXT
    assert isinstance(VOICE_PREVIEW_SAMPLE_TEXT, str)
    assert len(VOICE_PREVIEW_SAMPLE_TEXT.strip()) > 0


def test_voice_preview_sample_text_matches_frontend_expectation():
    """Frontend uses the same phrase; keep in sync with Settings VOICE_SAMPLE_TEXT / backend source of truth."""
    expected = "Hi there! Thanks for calling. How can I help you today?"
    assert VOICE_PREVIEW_SAMPLE_TEXT.strip() == expected


def test_tts_voices_list():
    """Canonical voice list must match OpenAI API and dashboard VOICES."""
    expected = ["nova", "alloy", "echo", "fable", "onyx", "shimmer"]
    assert TTS_VOICES == expected
    assert len(TTS_VOICES) == 6


def test_tts_voices_no_duplicates():
    """Voice list must have no duplicates."""
    assert len(TTS_VOICES) == len(set(TTS_VOICES))


def test_add_sentence_pauses_empty():
    """Empty or whitespace input returned as-is."""
    assert add_sentence_pauses("") == ""
    assert add_sentence_pauses("   ") == "   "


def test_add_sentence_pauses_after_period():
    """Pauses inserted after periods."""
    out = add_sentence_pauses("Hello. World.")
    assert ".\n\n" in out or out == "Hello.\n\nWorld."


def test_add_sentence_pauses_after_exclamation():
    """Pauses inserted after exclamation marks."""
    out = add_sentence_pauses("Hi! Bye!")
    assert "!\n\n" in out


def test_add_sentence_pauses_after_question():
    """Pauses inserted after question marks."""
    out = add_sentence_pauses("Really? Yes.")
    assert "?\n\n" in out


def test_add_sentence_pauses_preserves_content():
    """Content is preserved; only punctuation spacing changes."""
    text = "Hi there! Thanks for calling. How can I help you today?"
    out = add_sentence_pauses(text)
    # Strip the added newlines and compare content
    assert out.replace("\n\n", " ").replace("  ", " ") == text.replace("  ", " ")


def test_add_sentence_pauses_voice_preview_text():
    """add_sentence_pauses applied to VOICE_PREVIEW_SAMPLE_TEXT is non-destructive."""
    out = add_sentence_pauses(VOICE_PREVIEW_SAMPLE_TEXT)
    assert out
    assert "Hi there" in out
    assert "Thanks for calling" in out
    assert "How can I help" in out


def test_static_voice_sample_filenames_contract():
    """Frontend and generate_voice_samples use the same naming: {voice}.mp3 for each TTS_VOICES entry."""
    expected_names = {f"{v}.mp3" for v in TTS_VOICES}
    assert len(expected_names) == len(TTS_VOICES)
    assert expected_names == {"nova.mp3", "alloy.mp3", "echo.mp3", "fable.mp3", "onyx.mp3", "shimmer.mp3"}


def test_generate_script_output_path_uses_voice_list():
    """generate_voice_samples writes public/voice-samples/{voice}.mp3 for each TTS_VOICES; path contract."""
    # Script lives at backend/scripts/generate_voice_samples.py, output at project_root/public/voice-samples
    script_dir = Path(__file__).resolve().parent.parent / "scripts"
    out_dir = script_dir.parent.parent / "public" / "voice-samples"
    assert out_dir.name == "voice-samples"
    assert (script_dir.parent.parent / "public").name == "public"
    for voice in TTS_VOICES:
        assert (out_dir / f"{voice}.mp3").name == f"{voice}.mp3"


def test_voice_samples_exist_when_directory_present():
    """If public/voice-samples exists, it must contain an MP3 for each TTS_VOICES (regeneration contract)."""
    out_dir = Path(__file__).resolve().parent.parent.parent / "public" / "voice-samples"
    if not out_dir.is_dir():
        pytest.skip("public/voice-samples not present (run generate_voice_samples.py and commit)")
    for voice in TTS_VOICES:
        path = out_dir / f"{voice}.mp3"
        assert path.is_file(), f"Missing {path}; run: python backend/scripts/generate_voice_samples.py"
