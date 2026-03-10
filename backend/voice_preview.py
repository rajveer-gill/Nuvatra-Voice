"""
Single source of truth for voice preview samples and TTS text helpers.
Used by the generate_voice_samples script and by main.py for consistent preview/production TTS.
"""
import re

# Sample text played in the dashboard when users preview a voice. Change here then re-run generate_voice_samples.
VOICE_PREVIEW_SAMPLE_TEXT = "Hi there! Thanks for calling. How can I help you today?"

# Canonical list of OpenAI TTS voices. Must match OpenAI API (nova, alloy, echo, fable, onyx, shimmer).
TTS_VOICES = ["nova", "alloy", "echo", "fable", "onyx", "shimmer"]


def add_sentence_pauses(text: str) -> str:
    """Insert short pauses after periods, exclamation points, and question marks so sentences don't run together."""
    if not text or not text.strip():
        return text
    return re.sub(r"([.!?])\s*", r"\1\n\n", text).strip()
