"""Sentence chunking for progressive per-turn <Play> playback (Phase 2 TTS latency)."""
from voice_service import split_tts_chunks


def test_empty_returns_empty():
    assert split_tts_chunks("") == []
    assert split_tts_chunks("   ") == []


def test_single_sentence_is_one_chunk():
    """A one-sentence reply must behave exactly like today: a single <Play>."""
    assert split_tts_chunks("How can I help you today?") == ["How can I help you today?"]


def test_splits_multiple_sentences():
    chunks = split_tts_chunks(
        "We do have parking available. I can take a message for the team. "
        "Would you like me to do that?"
    )
    assert chunks == [
        "We do have parking available.",
        "I can take a message for the team.",
        "Would you like me to do that?",
    ]


def test_short_opener_is_its_own_first_chunk():
    """A short opener stays chunk 1 so the caller hears audio fast."""
    chunks = split_tts_chunks("Hi. I'd love to help you book with Jake this Friday.")
    assert chunks[0] == "Hi."
    assert len(chunks) == 2


def test_does_not_split_on_time_abbreviation():
    """'2 p.m.' must not be treated as a sentence end."""
    chunks = split_tts_chunks("Your appointment is Friday at 2 p.m. See you then!")
    assert chunks == ["Your appointment is Friday at 2 p.m. See you then!"]


def test_does_not_split_on_decimal():
    """A decimal price must not split."""
    chunks = split_tts_chunks("A long cut is $2.50 per minute. Want to book?")
    assert chunks == ["A long cut is $2.50 per minute.", "Want to book?"]


def test_does_not_split_on_title_abbreviation():
    chunks = split_tts_chunks("Dr. Smith is available Monday. Shall I book you?")
    assert chunks == ["Dr. Smith is available Monday.", "Shall I book you?"]


def test_tiny_fragment_merges_into_previous():
    """A tiny mid-reply fragment merges up rather than becoming its own TTS call."""
    chunks = split_tts_chunks("Your appointment with Jake is confirmed for Friday. Yes.")
    assert chunks == ["Your appointment with Jake is confirmed for Friday. Yes."]


def test_caps_chunk_count():
    """Many sentences collapse into at most max_chunks; the tail merges into the last."""
    text = " ".join(f"This is sentence number {n} in the reply." for n in range(8))
    chunks = split_tts_chunks(text, max_chunks=4)
    assert len(chunks) == 4
    # Nothing is dropped — the joined chunks reconstruct every sentence.
    assert chunks[-1].count("This is sentence") == 5
