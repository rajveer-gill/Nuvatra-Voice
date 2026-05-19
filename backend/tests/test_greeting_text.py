"""Phone greeting text includes receptionist name when configured."""

from __future__ import annotations

import main


def test_greeting_prepends_receptionist_name(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "Test Spa",
            "receptionist_name": "Ava",
            "greeting": "Thank you for calling {business_name}. How can I help?",
        },
    )
    monkeypatch.setattr(main, "_call_recording_enabled_for_tenant", lambda _t: False)
    monkeypatch.setattr(main, "_tenant_for_call_recording", lambda: None)
    text = main.get_greeting_text()
    assert text.startswith("Hi, I'm Ava.")
    assert "Test Spa" in text


def test_greeting_respects_custom_receptionist_placeholder(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "Test Spa",
            "receptionist_name": "Ava",
            "greeting": "Hi, this is {receptionist_name} at {business_name}.",
        },
    )
    monkeypatch.setattr(main, "_call_recording_enabled_for_tenant", lambda _t: False)
    monkeypatch.setattr(main, "_tenant_for_call_recording", lambda: None)
    text = main.get_greeting_text()
    assert text.startswith("Hi, this is Ava at Test Spa.")
    assert "Hi, I'm Ava" not in text
