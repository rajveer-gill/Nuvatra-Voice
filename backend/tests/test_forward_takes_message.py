"""When "take a message instead" is on, a caller asking for a person must NOT be forwarded —
the AI captures a message instead. Regression: a transfer number + the toggle both set caused
the call to dial the number, ignoring the toggle."""
import voice_service


def test_human_request_is_not_forwarded_when_take_message_on(monkeypatch):
    monkeypatch.setattr(voice_service.config_service, "transfer_takes_message", lambda *a, **k: True)
    assert (
        voice_service.should_forward_to_human("I'd like to talk to a real person", "")
        is False
    )


def test_human_request_forwards_when_take_message_off(monkeypatch):
    monkeypatch.setattr(voice_service.config_service, "transfer_takes_message", lambda *a, **k: False)
    assert (
        voice_service.should_forward_to_human("I'd like to talk to a real person", "")
        is True
    )


def test_non_human_input_never_forwards(monkeypatch):
    monkeypatch.setattr(voice_service.config_service, "transfer_takes_message", lambda *a, **k: False)
    assert voice_service.should_forward_to_human("what are your hours?", "") is False


def test_non_human_input_not_flagged_take_message(monkeypatch):
    # With the toggle on, a booking/other utterance must return False WITHOUT being treated as a
    # human request — regression: an early return logged human_request_takes_message every turn.
    logged = []
    monkeypatch.setattr(voice_service.config_service, "transfer_takes_message", lambda *a, **k: True)
    monkeypatch.setattr(voice_service, "voice_forward", lambda event, **k: logged.append(event))
    assert voice_service.should_forward_to_human("I'd like to book an appointment", "") is False
    assert logged == []  # not a human request → nothing logged
