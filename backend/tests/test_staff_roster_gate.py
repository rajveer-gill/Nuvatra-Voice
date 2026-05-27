"""Team roster must be configured before voice booking / AI answers."""

from __future__ import annotations

import main


def test_bookable_staff_requires_name_and_phone():
    info = {
        "staff": [
            {"id": "1", "name": "Alex", "phone": "+15551234567"},
            {"id": "2", "name": "No Phone", "phone": ""},
            {"id": "3", "name": "", "phone": "+15559876543"},
        ]
    }
    assert len(main.bookable_staff_members(info)) == 1
    assert main.staff_roster_ready_for_booking(info) is True


def test_staff_roster_not_ready_when_empty():
    assert main.staff_roster_ready_for_booking({"staff": []}) is False


def test_setup_status_warns_without_roster():
    body = main.get_setup_status(
        {
            "name": "Spa",
            "hours": "9-5",
            "forwarding_phone": "+15551111111",
            "address": "123 Main",
            "staff": [],
            "services": [{"id": "s1", "name": "Cut"}],
        }
    )
    assert body.get("roster_ready") is False
    assert any("Team roster" in w for w in body.get("warnings") or [])


def test_setup_status_warns_without_store_phone():
    body = main.get_setup_status(
        {
            "name": "Spa",
            "hours": "9-5",
            "forwarding_phone": "",
            "address": "123 Main",
            "staff": [{"id": "1", "name": "Alex", "phone": "+15551112222"}],
            "services": [{"id": "s1", "name": "Cut"}],
        }
    )
    assert body.get("forwarding_phone_ready") is False
    assert any("store phone number" in w for w in body.get("warnings") or [])


def test_roster_not_ready_twiml_includes_message_and_dial(monkeypatch):
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    twiml = str(
        main.twiml_roster_not_ready_handoff(
            "https://api.example.com",
            {"forwarding_phone": "+15557654321"},
            call_sid="CA123",
        )
    )
    assert "tts-audio" in twiml
    assert "+15557654321" in twiml.replace(" ", "")


def test_roster_not_ready_twiml_mentions_store_phone_when_missing(monkeypatch):
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    twiml = str(
        main.twiml_roster_not_ready_handoff(
            "https://api.example.com",
            {"forwarding_phone": ""},
            call_sid="CA123",
        )
    )
    assert "store phone number" in twiml.lower()
