"""Unit tests for parse_booking and booking requirement guards."""
import pytest
from main import (
    _ai_implies_committed_booking,
    _apply_booking_customer_name,
    _caller_indicated_service_choice,
    _caller_indicated_stylist_choice,
    _extract_booking_line_from_conversation,
    _format_appointment_details_confirmation_sms,
    _should_attempt_voice_booking_extraction,
    _strip_booking_directive_for_voice,
    _validate_booking_requirements,
    _voice_booking_nudge_message,
    parse_booking,
)


def test_parse_booking_valid():
    text = "BOOKING: John Doe|+15551234567|john@example.com|2025-03-15|10:30|Haircut"
    got = parse_booking(text)
    assert got is not None
    assert got["name"] == "John Doe"
    assert got["phone"] == "+15551234567"
    assert got["email"] == "john@example.com"
    assert got["date"] == "2025-03-15"
    assert got["time"] == "10:30"
    assert got["reason"] == "Haircut"


def test_parse_booking_minimal():
    text = "BOOKING: Jane|5551234567| |2025-03-20|14:00|Color"
    got = parse_booking(text)
    assert got is not None
    assert got["name"] == "Jane"
    assert got["date"] == "2025-03-20"
    assert got["time"] == "14:00"


def test_parse_booking_empty():
    assert parse_booking("") is None
    assert parse_booking(None) is None


def test_parse_booking_no_booking_marker():
    assert parse_booking("Just some text") is None
    assert parse_booking("Thanks for calling!") is None


def test_ai_implies_committed_booking_catches_change_acknowledgments():
    # Regression: the model narrated "I've updated your request to 3 PM" WITHOUT re-emitting the
    # BOOKING marker, so the mid-call change was lost. These phrases must trigger the extraction
    # safety net so the change still gets applied.
    assert _ai_implies_committed_booking("Alright, I've updated your request to 3:00 PM")
    assert _ai_implies_committed_booking("I have changed your appointment to Andrew")
    assert _ai_implies_committed_booking("I've switched your stylist to Jake")
    assert not _ai_implies_committed_booking("What service would you like?")


def test_parse_booking_realigns_dropped_empty_fields():
    # Regression: the model dropped an always-empty field ("Raj||2026-07-06|..." instead of
    # "Raj|||2026-07-06|..."), shifting the date into the email slot -> rejected as invalid_date
    # -> "scheduled" said but nothing booked. The parser must realign by the ISO date.
    for text in (
        "Great! BOOKING: Raj||2026-07-06|2:00 PM|Long Cut|Jake",  # dropped email
        "BOOKING: Raj|2026-07-06|2:00 PM|Long Cut|Jake",  # dropped phone AND email
        "BOOKING: Raj|||2026-07-06|2:00 PM|Long Cut|Jake",  # correct 7-field
    ):
        got = parse_booking(text)
        assert got is not None
        assert got["date"] == "2026-07-06"
        assert got["time"] == "2:00 PM"
        assert got["reason"] == "Long Cut"
        assert got["staff"] == "Jake"


def test_parse_booking_too_few_fields():
    text = "BOOKING: John|555"
    got = parse_booking(text)
    assert got is None


def test_parse_booking_with_staff_field():
    text = "BOOKING: Ann|+15550009999| |2025-04-01|15:00|Color|uuid-staff-1"
    got = parse_booking(text)
    assert got is not None
    assert got.get("staff") == "uuid-staff-1"


def test_parse_booking_with_leading_prose_same_line():
    text = "Awesome! BOOKING: Alex Pereira|||2026-05-19|3:00 PM|Nextiva|"
    got = parse_booking(text)
    assert got is not None
    assert got["name"] == "Alex Pereira"
    assert got["phone"] == ""
    assert got["email"] == ""
    assert got["date"] == "2026-05-19"
    assert got["time"] == "3:00 PM"
    assert got["reason"] == "Nextiva"


def test_parse_booking_multiline_prose_before_marker():
    text = "Sounds great.\nBOOKING: Sam|+15550001111|sam@x.com|2026-06-01|09:00|Cut|"
    got = parse_booking(text)
    assert got is not None
    assert got["name"] == "Sam"
    assert got["phone"] == "+15550001111"


def test_strip_booking_directive_for_voice():
    raw = "Great!\nBOOKING: X|y| |2026-01-02|10:00|Z|\nSee you then."
    assert "BOOKING" not in _strip_booking_directive_for_voice(raw)
    assert "Great" in _strip_booking_directive_for_voice(raw)


def test_validate_booking_requires_stylist_when_staff_configured(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "", "reason": "Haircut"}
    )
    assert not ok
    assert "which stylist" in (msg or "").lower()
    assert staff_id is None
    assert service is None


def test_validate_booking_requires_known_service_when_services_configured(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": ""}
    )
    assert not ok
    assert "which service" in (msg or "").lower()
    assert staff_id == "s1"
    assert service is None


def test_validate_booking_normalizes_service_name(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": "haircut please"},
        conversation_history=[{"role": "user", "content": "I'd like a haircut tomorrow at 2"}],
    )
    assert ok
    assert msg is None
    assert staff_id == "s1"
    assert service == "Haircut"


def test_caller_phone_ignores_model_placeholder():
    # The model sometimes copies the literal "phone" placeholder into the BOOKING phone field;
    # for voice, the caller's Twilio number is authoritative and must win.
    from conversation_service import _caller_phone_for_booking as f

    assert f("phone", "+19255551234") == "+19255551234"  # placeholder -> caller ID
    assert f("", "+19255551234") == "+19255551234"
    assert f(None, "+19255551234") == "+19255551234"
    assert f("+15551234567", "+19255551234") == "+15551234567"  # a real number is kept


def test_validate_booking_rejects_stylist_who_lacks_service(monkeypatch):
    # The chosen stylist must actually offer the chosen service — applies to mid-call changes too.
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [
                {"id": "s1", "name": "Mia", "service_ids": ["svc1"]},  # only Haircut
                {"id": "s2", "name": "Tom", "service_ids": ["svc2"]},  # only Color
            ],
            "services": [
                {"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30},
                {"id": "svc2", "name": "Color", "price": 50, "duration_minutes": 60},
            ],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": "Color"},
        conversation_history=[{"role": "user", "content": "I'd like Color with Mia"}],
    )
    assert not ok
    assert "mia doesn't do color" in (msg or "").lower()
    assert "tom" in (msg or "").lower()  # suggests the stylist who does offer it


def test_validate_booking_allows_stylist_who_offers_service(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia", "service_ids": ["svc1"]}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": "Haircut"},
        conversation_history=[{"role": "user", "content": "Haircut with Mia"}],
    )
    assert ok
    assert service == "Haircut"


def test_validate_booking_empty_service_ids_offers_everything(monkeypatch):
    # A stylist with no service_ids does every service — must not be rejected.
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],  # no service_ids
            "services": [{"id": "svc1", "name": "Color", "price": 50, "duration_minutes": 60}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": "Color"},
        conversation_history=[{"role": "user", "content": "Color with Mia"}],
    )
    assert ok
    assert service == "Color"


def test_validate_booking_rejects_auto_stylist_without_caller_choice(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "B", "reason": "Haircut", "name": "Sam", "date": "2026-06-02", "time": "14:00"},
        conversation_history=[{"role": "user", "content": "book a haircut tomorrow at 2 my name is Sam"}],
    )
    assert not ok
    assert "stylist" in (msg or "").lower()
    assert staff_id is None


def test_validate_booking_accepts_stylist_when_caller_named_one(monkeypatch):
    biz = {
        "staff": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
        "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
    }
    monkeypatch.setattr("config_service.get_business_info", lambda: biz)
    history = [
        {"role": "user", "content": "Book a haircut with B tomorrow at 2pm, I'm Sam"},
    ]
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "B", "reason": "Haircut", "name": "Sam", "date": "2026-06-02", "time": "14:00"},
        conversation_history=history,
    )
    assert ok
    assert staff_id == "s2"
    assert service == "Haircut"


def test_validate_booking_accepts_any_stylist_phrase(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, _, staff_id, _ = _validate_booking_requirements(
        {"staff": "A", "reason": "Haircut", "name": "Sam", "date": "2026-06-02", "time": "14:00"},
        conversation_history=[{"role": "user", "content": "haircut tomorrow 2pm anyone is fine"}],
    )
    assert ok
    assert staff_id == "s1"


def test_voice_booking_nudge_after_three_turns():
    history = [
        {"role": "user", "content": "I want to book an appointment"},
        {"role": "assistant", "content": "Sure!"},
        {"role": "user", "content": "Tomorrow afternoon"},
        {"role": "assistant", "content": "Great!"},
        {"role": "user", "content": "Around 2pm"},
    ]
    nudge = _voice_booking_nudge_message(history)
    assert nudge is not None
    assert "BOOKING REMINDER" in nudge


def test_voice_booking_nudge_prioritizes_service_before_stylist(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
            "services": [{"id": "svc1", "name": "Short Cut", "price": 20, "duration_minutes": 30}],
        },
    )
    history = [
        {"role": "user", "content": "I want to book tomorrow"},
        {"role": "assistant", "content": "Sure"},
        {"role": "user", "content": "2pm works"},
        {"role": "assistant", "content": "Got it"},
        {"role": "user", "content": "My name is Raj"},
    ]
    nudge = _voice_booking_nudge_message(history)
    assert nudge is not None
    assert "service" in nudge.lower()
    assert "Do NOT ask which stylist yet" in nudge


def test_voice_booking_nudge_service_at_two_turns(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
            "services": [{"id": "svc1", "name": "Short Cut", "price": 20, "duration_minutes": 30}],
        },
    )
    history = [
        {"role": "user", "content": "I'd like an appointment tomorrow at 3"},
        {"role": "assistant", "content": "Sure"},
        {"role": "user", "content": "Raj"},
    ]
    nudge = _voice_booking_nudge_message(history)
    assert nudge is not None
    assert "service" in nudge.lower()


def test_ai_implies_committed_booking_detects_false_confirm():
    assert _ai_implies_committed_booking("You're all set for Tuesday at 2!")
    assert _ai_implies_committed_booking(
        "Great choice, Raj! I have you scheduled for a Long Cut with Jake tomorrow at 3:00 PM. See you then!"
    )
    assert not _ai_implies_committed_booking("Which stylist would you like?")


def test_should_attempt_voice_booking_extraction_on_scheduled_wording(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "j1", "name": "Jake"}],
            "services": [{"id": "s1", "name": "Long Cut"}],
        },
    )
    history = [
        {"role": "user", "content": "I want to book a haircut"},
        {"role": "user", "content": "With Jake tomorrow at 3"},
        {"role": "user", "content": "Long cut please"},
    ]
    ai = "Great, I have you scheduled for a Long Cut with Jake tomorrow at 3 PM. See you then!"
    assert _should_attempt_voice_booking_extraction(history, ai) is True


def test_validate_booking_does_not_repeat_service_when_user_answered(monkeypatch):
    biz = {
        "staff": [{"id": "j1", "name": "Jake"}],
        "services": [{"id": "s1", "name": "Long Cut", "price": 45, "duration_minutes": 45}],
    }
    monkeypatch.setattr("config_service.get_business_info", lambda: biz)
    history = [
        {"role": "user", "content": "Book with Jake tomorrow at 3"},
        {"role": "assistant", "content": "Which service would you like with Jake? Short Cut or Long Cut."},
        {"role": "user", "content": "long cut"},
    ]
    # Relative future date keeps this deterministic: is_past_closing_for_date rejects
    # only when the booking date == today (after closing), so a hardcoded "today" flaked
    # in the afternoon. Three days out is never today in any timezone.
    from datetime import date, timedelta

    future_date = (date.today() + timedelta(days=3)).isoformat()
    ok, msg, staff_id, service = _validate_booking_requirements(
        {
            "staff": "Jake",
            "reason": "Long Cut",
            "name": "Raj",
            "date": future_date,
            "time": "15:00",
        },
        conversation_history=history,
    )
    assert ok
    assert msg is None
    assert staff_id == "j1"
    assert service == "Long Cut"


def test_extract_booking_rejects_misaligned_time(monkeypatch):
    def fake_create(**kwargs):
        class Msg:
            content = "BOOKING: Raj|||2026-06-09|Jake|Long Cut|"

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]

        return Resp()

    monkeypatch.setattr("main.client.chat.completions.create", fake_create)
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "j1", "name": "Jake"}],
            "services": [{"id": "s1", "name": "Long Cut"}],
        },
    )
    got = _extract_booking_line_from_conversation(
        [{"role": "user", "content": "Jake tomorrow at 3 long cut"}],
        caller_memory={"name": "Raj"},
    )
    assert got is None


def test_extract_booking_line_from_conversation(monkeypatch):
    captured = {}
    # Use a clearly-future date (booking validation rejects past dates), computed
    # dynamically so the test never goes stale as the calendar advances.
    from datetime import timedelta
    import business_hours

    future_date = (business_hours.business_local_now({}) + timedelta(days=5)).date().isoformat()

    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        class Msg:
            content = f"BOOKING: Raj|||{future_date}|15:00|Long Cut|Jake"

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]

        return Resp()

    monkeypatch.setattr("main.client.chat.completions.create", fake_create)
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {
            "staff": [{"id": "j1", "name": "Jake"}],
            "services": [{"id": "s1", "name": "Long Cut"}],
        },
    )
    got = _extract_booking_line_from_conversation(
        [
            {"role": "user", "content": "Book with Jake tomorrow at 3"},
            {"role": "assistant", "content": "Long cut?"},
            {"role": "user", "content": "Yes long cut, I'm Raj"},
        ],
        caller_memory={"name": "Raj"},
    )
    assert got is not None
    assert got["name"] == "Raj"
    assert got["date"] == future_date
    assert got["staff"] == "Jake"


def test_apply_booking_customer_name_replaces_stylist_with_memory(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {"staff": [{"id": "s1", "name": "Tom"}]},
    )
    booking = {"name": "Tom", "staff": "Tom"}
    _apply_booking_customer_name(booking, caller_memory={"name": "Sarah"})
    assert booking["name"] == "Sarah"


def test_apply_booking_customer_name_clears_stylist_without_memory(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {"staff": [{"id": "s1", "name": "Tom"}]},
    )
    booking = {"name": "Tom", "staff": "Tom"}
    _apply_booking_customer_name(booking, caller_memory=None)
    assert booking["name"] == ""


def test_format_confirmation_sms_shows_customer_and_stylist(monkeypatch):
    monkeypatch.setattr(
        "config_service.get_business_info",
        lambda: {"staff": [{"id": "s1", "name": "Tom"}]},
    )
    msg = _format_appointment_details_confirmation_sms(
        {
            "name": "Sarah",
            "phone": "+15551234567",
            "date": "2026-05-29",
            "time": "14:00",
            "reason": "Short Cut",
            "status": "pending_customer",
            "staff_id": "s1",
        }
    )
    assert "Customer: Sarah" in msg
    assert "Stylist: Tom" in msg
    assert "Name:" not in msg


def test_validate_booking_rejects_same_day_after_hours(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    biz = {
        "name": "Test Salon",
        "hours": "Monday-Friday: 9 AM - 5 PM",
        "timezone": "America/Los_Angeles",
        "services": [{"id": "s1", "name": "Haircut"}],
        "staff": [{"id": "j1", "name": "Jake"}],
    }
    monkeypatch.setattr("config_service.get_business_info", lambda: biz)
    fixed = datetime(2026, 6, 4, 18, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    monkeypatch.setattr(
        "business_hours.business_local_now", lambda info, now=None: fixed
    )
    ok, msg, _, _ = _validate_booking_requirements(
        {
            "name": "Alex",
            "date": "2026-06-04",
            "time": "15:00",
            "reason": "Haircut",
            "staff": "Jake",
        },
        conversation_history=[
            {"role": "user", "content": "Book with Jake today at 3"},
        ],
    )
    assert ok is False
    assert msg
    assert "closed for today" in msg.lower()

