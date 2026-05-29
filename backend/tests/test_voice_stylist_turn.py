"""Voice path fixes: Latin-script override and no-speech race guards."""

from main import _conversation_prefers_english_stt, _text_looks_latin


def test_text_looks_latin_english():
    assert _text_looks_latin("Tom, please.") is True
    assert _text_looks_latin("Book with Jake") is True


def test_conversation_prefers_english_after_latin_utterance():
    call_data = {
        "detected_language": "Hindi",
        "conversation_history": [{"role": "user", "content": "Tom, please."}],
    }
    assert _conversation_prefers_english_stt(call_data) is True


def test_conversation_stays_non_latin_without_latin_history():
    call_data = {
        "detected_language": "Hindi",
        "conversation_history": [],
    }
    assert _conversation_prefers_english_stt(call_data) is False
