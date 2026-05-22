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
            "address": "123 Main",
            "staff": [],
            "services": [{"id": "s1", "name": "Cut"}],
        }
    )
    assert body.get("roster_ready") is False
    assert any("Team roster" in w or "team member" in w.lower() for w in body.get("warnings") or [])


def test_roster_not_ready_twiml_plays_message_and_hangup(monkeypatch):
    monkeypatch.setattr(main, "get_tts_voice", lambda: "fable")
    twiml = str(
        main.twiml_roster_not_ready_handoff(
            "https://api.example.com",
            {"staff": []},
            call_sid="CA123",
        )
    )
    assert "tts-audio" in twiml
    assert "Goodbye" in twiml
    assert "<Dial" not in twiml


def test_booking_requires_staff_when_multiple_roster_members():
    info = {
        "staff": [
            {"id": "a", "name": "Sam", "phone": "+15551111111"},
            {"id": "b", "name": "Alex", "phone": "+15552222222"},
        ],
    }
    assert main._booking_staff_id_from_roster({"staff": ""}, info) is None
    assert main._booking_staff_id_from_roster({"staff": "Alex"}, info) == "b"


def test_booking_auto_assigns_single_roster_member():
    info = {"staff": [{"id": "only", "name": "Jamie", "phone": "+15551111111"}]}
    assert main._booking_staff_id_from_roster({"staff": ""}, info) == "only"
