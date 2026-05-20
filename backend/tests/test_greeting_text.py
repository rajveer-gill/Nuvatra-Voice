"""Phone greeting text: placeholders, receptionist prepend, recording disclosure order."""

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


def test_user_custom_greeting_template(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "Call Surge Demo",
            "receptionist_name": "Jordan",
            "greeting": "Thank you for calling {business_name}. I am {receptionist_name}. What is up?",
        },
    )
    monkeypatch.setattr(main, "_call_recording_enabled_for_tenant", lambda _t: False)
    monkeypatch.setattr(main, "_tenant_for_call_recording", lambda: None)
    payload = main.build_phone_greeting_payload(main.get_business_info(), None)
    assert payload["main_greeting"] == (
        "Thank you for calling Call Surge Demo. I am Jordan. What is up?"
    )
    assert payload["used_default_template"] is False
    assert payload["prepended_receptionist"] is False


def test_recording_disclosure_always_after_main_greeting(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "Test Spa",
            "receptionist_name": "Ava",
            "greeting": "Thank you for calling {business_name}. What is up?",
        },
    )
    monkeypatch.setattr(main, "_call_recording_enabled_for_tenant", lambda _t: True)
    monkeypatch.setattr(main, "_tenant_for_call_recording", lambda: {"client_id": "test"})
    text = main.get_greeting_text()
    assert "What is up?" in text
    assert text.endswith(main.RECORDING_DISCLOSURE_TEXT)
    assert text.index("What is up?") < text.index("recorded")


def test_business_name_from_tenant_when_config_name_empty(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "",
            "receptionist_name": "Ava",
            "greeting": "Thank you for calling {business_name}.",
        },
    )
    tenant = {"name": "Admin Tenant Name", "client_id": "test-spa"}
    payload = main.build_phone_greeting_payload(main.get_business_info(), tenant)
    assert payload["placeholders"]["business_name"] == "Admin Tenant Name"
    assert "Admin Tenant Name" in payload["main_greeting"]
