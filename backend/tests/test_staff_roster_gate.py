"""Team roster and store phone gate inbound voice and setup status."""

from __future__ import annotations

from urllib.parse import unquote

import main
from routers import business as business_router


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


def test_voice_receptionist_requires_roster_store_phone_and_services():
    ready = {
        "forwarding_phone": "+15551111111",
        "staff": [{"id": "1", "name": "Alex", "phone": ""}],
        "services": [{"id": "s1", "name": "Cut"}],
    }
    assert main.voice_receptionist_ready(ready) is True
    # Missing any one of the three → not ready.
    assert main.voice_receptionist_ready({**ready, "forwarding_phone": ""}) is False
    assert main.voice_receptionist_ready({**ready, "staff": []}) is False
    assert main.voice_receptionist_ready({**ready, "services": []}) is False


def test_services_configured_helper():
    assert main.services_configured({"services": [{"id": "s1", "name": "Cut"}]}) is True
    assert main.services_configured({"services": []}) is False
    assert main.services_configured({}) is False


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
    body = business_router.get_setup_status(
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
    body = business_router.get_setup_status(
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
    assert any("transfer number" in w for w in body.get("warnings") or [])


def test_take_a_message_satisfies_handoff_without_store_phone():
    """The toggle is an alternative to a transfer number, not an addition."""
    base = {"staff": [{"id": "1", "name": "Alex", "phone": ""}], "services": [{"id": "s1", "name": "Cut"}]}
    # No phone + no toggle => not ready.
    assert main.voice_receptionist_ready({**base, "forwarding_phone": ""}) is False
    # No phone but toggle on => ready (AI takes a message instead of dialing).
    assert (
        main.voice_receptionist_ready(
            {**base, "forwarding_phone": "", "transfer_takes_message": True}
        )
        is True
    )
    # A real transfer number alone (toggle off) is still a valid handoff path.
    assert (
        main.voice_receptionist_ready(
            {**base, "forwarding_phone": "+15551111111", "transfer_takes_message": False}
        )
        is True
    )


def test_human_handoff_configured_either_path():
    assert main.human_handoff_configured({"forwarding_phone": "+15551111111"}) is True
    assert main.human_handoff_configured({"transfer_takes_message": True}) is True
    assert main.human_handoff_configured({"forwarding_phone": ""}) is False


def test_setup_status_take_message_clears_missing_and_warning():
    body = business_router.get_setup_status(
        {
            "name": "Spa",
            "hours": "9-5",
            "forwarding_phone": "",
            "transfer_takes_message": True,
            "address": "123 Main",
            "staff": [{"id": "1", "name": "Alex", "phone": ""}],
            "services": [{"id": "s1", "name": "Cut"}],
        }
    )
    assert body.get("transfer_takes_message") is True
    assert body.get("voice_ready") is True
    # Store phone no longer counts as a missing required field.
    assert "Store phone (real person)" not in (body.get("missing") or [])
    # No handoff warning when the toggle is on.
    assert not any("transfer number" in w for w in body.get("warnings") or [])


def test_setup_status_warning_mentions_toggle_when_no_handoff():
    body = business_router.get_setup_status(
        {
            "name": "Spa",
            "hours": "9-5",
            "forwarding_phone": "",
            "address": "123 Main",
            "staff": [{"id": "1", "name": "Alex", "phone": ""}],
            "services": [{"id": "s1", "name": "Cut"}],
        }
    )
    warning = next((w for w in body.get("warnings") or [] if "transfer number" in w), "")
    assert "take a message" in warning.lower()


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
