"""Team roster and store phone gate inbound voice and setup status."""

from __future__ import annotations

from urllib.parse import unquote

import main


def test_staff_on_roster_requires_name_only():
    info = {
        "staff": [
            {"id": "1", "name": "Alex", "phone": "+15551234567"},
            {"id": "2", "name": "No Phone", "phone": ""},
            {"id": "3", "name": "", "phone": "+15559876543"},
        ]
    }
    assert len(main.staff_on_roster(info)) == 2
    assert main.staff_roster_ready_for_booking(info) is True


def test_staff_roster_not_ready_when_empty():
    assert main.staff_roster_ready_for_booking({"staff": []}) is False


def test_voice_receptionist_requires_roster_and_store_phone():
    ready = {
        "forwarding_phone": "+15551111111",
        "staff": [{"id": "1", "name": "Alex", "phone": ""}],
    }
    assert main.voice_receptionist_ready(ready) is True
    assert main.voice_receptionist_ready({"forwarding_phone": "", "staff": ready["staff"]}) is False
    assert main.voice_receptionist_ready({"forwarding_phone": "+15551111111", "staff": []}) is False


def test_setup_transfers_only_when_store_phone_without_roster():
    gap = {"forwarding_phone": "+15551111111", "staff": []}
    assert main.setup_transfers_to_store_after_message(gap) is True
    assert main.setup_transfers_to_store_after_message({"forwarding_phone": "", "staff": []}) is False
    assert main.setup_transfers_to_store_after_message(
        {"forwarding_phone": "", "staff": [{"id": "1", "name": "Alex", "phone": ""}]}
    ) is False


def test_setup_not_ready_call_message_roster_only_gap_mentions_transfer():
    msg = main.setup_not_ready_call_message({"staff": [], "forwarding_phone": "+15551111111"})
    assert "roster" in msg.lower()
    assert "transfer" in msg.lower()


def test_setup_not_ready_call_message_no_store_phone_no_transfer_hint():
    msg = main.setup_not_ready_call_message({"staff": [], "forwarding_phone": ""})
    assert "transfer" not in msg.lower()
    assert "store phone" in msg.lower() or "settings" in msg.lower()


def test_setup_status_roster_only_gap_flag():
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
    assert body.get("roster_only_gap") is True
    assert body.get("voice_ready") is False


def test_setup_status_warns_without_store_phone():
    body = main.get_setup_status(
        {
            "name": "Spa",
            "hours": "9-5",
            "forwarding_phone": "",
            "address": "123 Main",
            "staff": [{"id": "1", "name": "Alex", "phone": ""}],
            "services": [{"id": "s1", "name": "Cut"}],
        }
    )
    assert body.get("forwarding_phone_ready") is False
    assert body.get("roster_only_gap") is False
    assert any("store phone number" in w for w in body.get("warnings") or [])


def test_setup_not_ready_twiml_dials_store_when_roster_only_gap(monkeypatch):
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    twiml = str(
        main.twiml_setup_not_ready_handoff(
            "https://api.example.com",
            {"forwarding_phone": "+15557654321", "staff": []},
            call_sid="CA123",
        )
    )
    assert "tts-audio" in twiml
    assert "+15557654321" in twiml.replace(" ", "")
    assert "transfer" in unquote(twiml).lower()


def test_setup_not_ready_twiml_no_dial_without_store_phone(monkeypatch):
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    twiml = str(
        main.twiml_setup_not_ready_handoff(
            "https://api.example.com",
            {"forwarding_phone": "", "staff": []},
            call_sid="CA123",
        )
    )
    assert "<Dial" not in twiml
    decoded = unquote(twiml).lower()
    assert "goodbye" in decoded
