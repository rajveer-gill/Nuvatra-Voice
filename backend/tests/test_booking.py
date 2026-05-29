"""Unit tests for parse_booking and booking requirement guards."""
import pytest
from main import (
    _apply_booking_customer_name,
    _format_appointment_details_confirmation_sms,
    _strip_booking_directive_for_voice,
    _validate_booking_requirements,
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
        "main.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "", "reason": "Haircut"}
    )
    assert not ok
    assert "choose a stylist" in (msg or "").lower()
    assert staff_id is None
    assert service is None


def test_validate_booking_requires_known_service_when_services_configured(monkeypatch):
    monkeypatch.setattr(
        "main.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": ""}
    )
    assert not ok
    assert "choose a service" in (msg or "").lower()
    assert staff_id == "s1"
    assert service is None


def test_validate_booking_normalizes_service_name(monkeypatch):
    monkeypatch.setattr(
        "main.get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = _validate_booking_requirements(
        {"staff": "Mia", "reason": "haircut please"}
    )
    assert ok
    assert msg is None
    assert staff_id == "s1"
    assert service == "Haircut"


def test_apply_booking_customer_name_replaces_stylist_with_memory(monkeypatch):
    monkeypatch.setattr(
        "main.get_business_info",
        lambda: {"staff": [{"id": "s1", "name": "Tom"}]},
    )
    booking = {"name": "Tom", "staff": "Tom"}
    _apply_booking_customer_name(booking, caller_memory={"name": "Sarah"})
    assert booking["name"] == "Sarah"


def test_apply_booking_customer_name_clears_stylist_without_memory(monkeypatch):
    monkeypatch.setattr(
        "main.get_business_info",
        lambda: {"staff": [{"id": "s1", "name": "Tom"}]},
    )
    booking = {"name": "Tom", "staff": "Tom"}
    _apply_booking_customer_name(booking, caller_memory=None)
    assert booking["name"] == ""


def test_format_confirmation_sms_shows_customer_and_stylist(monkeypatch):
    monkeypatch.setattr(
        "main.get_business_info",
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
